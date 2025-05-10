import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
import os # 추가
import datetime
import pytz
from google.oauth2 import service_account
from googleapiclient.discovery import build
import requests
import json
import xml.etree.ElementTree as ET

# PRD에서 가져온 API 키 및 설정값 (Heroku Config Vars 사용 권장)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TODOIST_API_URL = "https://api.todoist.com/rest/v2/tasks" # 이 값은 환경 변수로 할 필요는 없을 수 있습니다.
TODOIST_API_TOKEN = os.environ.get("TODOIST_API_TOKEN")
TODOIST_PROJECT_ID = os.environ.get("TODOIST_PROJECT_ID") # 특정 프로젝트 ID
GOOGLE_CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID", "anVzdGljZWt5dW5nbmFtQGdtYWlsLmNvbQ") # 기본값 설정 가능
WEATHER_API_URL = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0" # 고정값
WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY")
DEFAULT_WEATHER_LOCATION = os.environ.get("DEFAULT_WEATHER_LOCATION", "경상남도 창원시 성산구") # 기본값 설정 가능
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")  # 서비스 계정 JSON 내용

# 로깅 설정
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 위 코드에서 os.environ.get()으로 불러오는 변수들이 모두 설정되어 있는지 확인하는 로직 추가 (선택적이지만 권장)
if not all([TELEGRAM_BOT_TOKEN, TODOIST_API_TOKEN, WEATHER_API_KEY]):
    logger.error("필수 환경 변수가 설정되지 않았습니다! (TELEGRAM_BOT_TOKEN, TODOIST_API_TOKEN, WEATHER_API_KEY)")
    # 적절한 종료 또는 오류 처리 로직
    exit() # 예시: 프로그램 종료

# Google Calendar API 설정
def get_calendar_service():
    if not GOOGLE_CREDENTIALS_JSON:
        logger.error("Google Calendar API 자격 증명이 설정되지 않았습니다.")
        return None
    
    try:
        # 환경 변수에서 가져온 JSON 문자열을 임시 파일로 저장
        import json
        import tempfile
        
        credentials_info = json.loads(GOOGLE_CREDENTIALS_JSON)
        
        with tempfile.NamedTemporaryFile(mode='w+', suffix='.json', delete=False) as temp:
            json.dump(credentials_info, temp)
            temp_filename = temp.name
        
        # 서비스 계정 인증 정보 생성
        credentials = service_account.Credentials.from_service_account_file(
            temp_filename, 
            scopes=['https://www.googleapis.com/auth/calendar.readonly']
        )
        
        # 임시 파일 삭제
        os.unlink(temp_filename)
        
        # Calendar API 서비스 생성
        service = build('calendar', 'v3', credentials=credentials)
        return service
    
    except Exception as e:
        logger.error(f"Google Calendar API 서비스 생성 중 오류 발생: {e}")
        return None

# --- 서비스 연동 함수 (나중에 구현) ---
async def get_google_calendar_events(date_type: str):
    service = get_calendar_service()
    if not service:
        return "구글 캘린더 연동에 실패했습니다. 관리자에게 문의하세요."
    
    # 한국 시간대 설정
    korea_tz = pytz.timezone('Asia/Seoul')
    now = datetime.datetime.now(korea_tz)
    
    # 요청된 날짜 범위에 따라 시작/종료 시간 설정
    if date_type == "오늘":
        start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_time = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        title = "오늘"
    elif date_type == "내일":
        tomorrow = now + datetime.timedelta(days=1)
        start_time = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
        end_time = tomorrow.replace(hour=23, minute=59, second=59, microsecond=999999)
        title = "내일"
    elif date_type == "이번주":
        # 이번 주 월요일을 찾습니다
        start_time = now - datetime.timedelta(days=now.weekday())
        start_time = start_time.replace(hour=0, minute=0, second=0, microsecond=0)
        # 이번 주 일요일 (월요일 + 6일)
        end_time = start_time + datetime.timedelta(days=6)
        end_time = end_time.replace(hour=23, minute=59, second=59, microsecond=999999)
        title = "이번 주"
    elif date_type == "다음주":
        # 다음 주 월요일 (이번 주 월요일 + 7일)
        next_monday = now - datetime.timedelta(days=now.weekday()) + datetime.timedelta(days=7)
        start_time = next_monday.replace(hour=0, minute=0, second=0, microsecond=0)
        # 다음 주 일요일 (다음 주 월요일 + 6일)
        end_time = start_time + datetime.timedelta(days=6)
        end_time = end_time.replace(hour=23, minute=59, second=59, microsecond=999999)
        title = "다음 주"
    else:
        return "알 수 없는 기간입니다."
    
    # 시간을 ISO 형식으로 변환
    start_time_iso = start_time.isoformat()
    end_time_iso = end_time.isoformat()
    
    try:
        logger.info(f"구글 캘린더 정보 요청: {date_type} ({start_time_iso} ~ {end_time_iso})")
        
        # 이벤트 검색 실행
        events_result = service.events().list(
            calendarId=GOOGLE_CALENDAR_ID,
            timeMin=start_time_iso,
            timeMax=end_time_iso,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        if not events:
            return f"{title}의 일정이 없습니다."
        
        # 이벤트 정보 포맷팅
        event_list = []
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            
            # 날짜 또는 시간 파싱
            if 'T' in start:  # 날짜와 시간이 모두 있는 경우 (dateTime)
                event_start = datetime.datetime.fromisoformat(start.replace('Z', '+00:00')).astimezone(korea_tz)
                start_str = event_start.strftime('%Y-%m-%d %H:%M')
            else:  # 종일 이벤트인 경우 (date)
                start_str = start
            
            event_list.append(f"• {start_str}: {event['summary']}")
        
        return "\n".join(event_list)
    
    except Exception as e:
        logger.error(f"구글 캘린더 이벤트 조회 중 오류 발생: {e}")
        return f"구글 캘린더 정보를 가져오는 중 오류가 발생했습니다: {str(e)}"

async def get_todoist_tasks(date_type: str):
    if not TODOIST_API_TOKEN:
        return "Todoist API 토큰이 설정되지 않았습니다. 관리자에게 문의하세요."
    
    headers = {
        "Authorization": f"Bearer {TODOIST_API_TOKEN}",
        "Content-Type": "application/json"
    }
    
    # 한국 시간대 설정
    korea_tz = pytz.timezone('Asia/Seoul')
    now = datetime.datetime.now(korea_tz)
    
    # 최대한 단순한 필터 사용하기
    try:
        if date_type == "오늘":
            # 프로젝트 ID가 있으면 해당 프로젝트의 오늘 마감 작업만 필터링
            if TODOIST_PROJECT_ID:
                # REST API를 통해 모든 작업을 가져온 후 수동으로 필터링
                response = requests.get(TODOIST_API_URL, headers=headers)
                
                if response.status_code != 200:
                    logger.error(f"Todoist API 오류: {response.status_code}, {response.text}")
                    return f"Todoist API 요청 중 오류가 발생했습니다. 상태 코드: {response.status_code}"
                
                all_tasks = response.json()
                
                # 프로젝트 ID와 마감일 기준으로 수동 필터링
                today_str = now.strftime("%Y-%m-%d")
                filtered_tasks = []
                
                for task in all_tasks:
                    # 프로젝트 ID 일치 여부 확인
                    if str(task.get('project_id', '')) != TODOIST_PROJECT_ID:
                        continue
                    
                    # 마감일 확인
                    due = task.get('due', {})
                    if due and 'date' in due:
                        due_date = due['date'].split('T')[0]  # 시간 부분 제거
                        if due_date == today_str:
                            filtered_tasks.append(task)
                
                tasks = filtered_tasks
            else:
                # 프로젝트 ID가 없으면 간단한 필터 사용
                response = requests.get(
                    TODOIST_API_URL,
                    headers=headers,
                    params={"filter": "today"}
                )
                
                if response.status_code != 200:
                    logger.error(f"Todoist API 오류: {response.status_code}, {response.text}")
                    return f"Todoist API 요청 중 오류가 발생했습니다. 상태 코드: {response.status_code}"
                
                tasks = response.json()
            
            title = "오늘"
            
        elif date_type == "내일":
            # 내일에 대해서도 동일한 로직 적용
            tomorrow = now + datetime.timedelta(days=1)
            tomorrow_str = tomorrow.strftime("%Y-%m-%d")
            
            if TODOIST_PROJECT_ID:
                response = requests.get(TODOIST_API_URL, headers=headers)
                
                if response.status_code != 200:
                    logger.error(f"Todoist API 오류: {response.status_code}, {response.text}")
                    return f"Todoist API 요청 중 오류가 발생했습니다. 상태 코드: {response.status_code}"
                
                all_tasks = response.json()
                filtered_tasks = []
                
                for task in all_tasks:
                    if str(task.get('project_id', '')) != TODOIST_PROJECT_ID:
                        continue
                    
                    due = task.get('due', {})
                    if due and 'date' in due:
                        due_date = due['date'].split('T')[0]
                        if due_date == tomorrow_str:
                            filtered_tasks.append(task)
                
                tasks = filtered_tasks
            else:
                response = requests.get(
                    TODOIST_API_URL,
                    headers=headers,
                    params={"filter": "tomorrow"}
                )
                
                if response.status_code != 200:
                    logger.error(f"Todoist API 오류: {response.status_code}, {response.text}")
                    return f"Todoist API 요청 중 오류가 발생했습니다. 상태 코드: {response.status_code}"
                
                tasks = response.json()
            
            title = "내일"
            
        elif date_type == "이번주":
            # 이번 주에 대해서도 수동 필터링 적용
            today_str = now.strftime("%Y-%m-%d")
            end_of_week = now + datetime.timedelta(days=7-now.weekday())
            end_of_week_str = end_of_week.strftime("%Y-%m-%d")
            
            if TODOIST_PROJECT_ID:
                response = requests.get(TODOIST_API_URL, headers=headers)
                
                if response.status_code != 200:
                    logger.error(f"Todoist API 오류: {response.status_code}, {response.text}")
                    return f"Todoist API 요청 중 오류가 발생했습니다. 상태 코드: {response.status_code}"
                
                all_tasks = response.json()
                filtered_tasks = []
                
                for task in all_tasks:
                    if str(task.get('project_id', '')) != TODOIST_PROJECT_ID:
                        continue
                    
                    due = task.get('due', {})
                    if due and 'date' in due:
                        due_date = due['date'].split('T')[0]
                        if today_str <= due_date <= end_of_week_str:
                            filtered_tasks.append(task)
                
                tasks = filtered_tasks
            else:
                # 간단한 일주일 필터
                response = requests.get(
                    TODOIST_API_URL,
                    headers=headers,
                    params={"filter": "7 days"}
                )
                
                if response.status_code != 200:
                    logger.error(f"Todoist API 오류: {response.status_code}, {response.text}")
                    return f"Todoist API 요청 중 오류가 발생했습니다. 상태 코드: {response.status_code}"
                
                tasks = response.json()
            
            title = "이번 주"
            
        elif date_type == "다음주":
            # 다음 주에 대해서도 수동 필터링 적용
            next_week_start = now + datetime.timedelta(days=7-now.weekday())
            next_week_start_str = next_week_start.strftime("%Y-%m-%d")
            next_week_end = next_week_start + datetime.timedelta(days=6)
            next_week_end_str = next_week_end.strftime("%Y-%m-%d")
            
            if TODOIST_PROJECT_ID:
                response = requests.get(TODOIST_API_URL, headers=headers)
                
                if response.status_code != 200:
                    logger.error(f"Todoist API 오류: {response.status_code}, {response.text}")
                    return f"Todoist API 요청 중 오류가 발생했습니다. 상태 코드: {response.status_code}"
                
                all_tasks = response.json()
                filtered_tasks = []
                
                for task in all_tasks:
                    if str(task.get('project_id', '')) != TODOIST_PROJECT_ID:
                        continue
                    
                    due = task.get('due', {})
                    if due and 'date' in due:
                        due_date = due['date'].split('T')[0]
                        if next_week_start_str <= due_date <= next_week_end_str:
                            filtered_tasks.append(task)
                
                tasks = filtered_tasks
            else:
                # 직접 API 필터링은 복잡해서 모든 작업을 가져와서 수동으로 필터링
                response = requests.get(TODOIST_API_URL, headers=headers)
                
                if response.status_code != 200:
                    logger.error(f"Todoist API 오류: {response.status_code}, {response.text}")
                    return f"Todoist API 요청 중 오류가 발생했습니다. 상태 코드: {response.status_code}"
                
                all_tasks = response.json()
                filtered_tasks = []
                
                for task in all_tasks:
                    due = task.get('due', {})
                    if due and 'date' in due:
                        due_date = due['date'].split('T')[0]
                        if next_week_start_str <= due_date <= next_week_end_str:
                            filtered_tasks.append(task)
                
                tasks = filtered_tasks
            
            title = "다음 주"
            
        else:
            return "알 수 없는 기간입니다."
        
        if not tasks:
            return f"{title} 예정된 작업이 없습니다."
        
        # 작업 정보 포맷팅
        task_list = []
        for task in tasks:
            due_date = task.get('due', {})
            due_str = due_date.get('date', '날짜 없음') if due_date else '날짜 없음'
            
            # ISO 날짜 형식을 보기 쉬운 형태로 변환
            if due_str and due_str != '날짜 없음' and 'T' in due_str:
                due_datetime = datetime.datetime.fromisoformat(due_str.replace('Z', '+00:00')).astimezone(korea_tz)
                due_str = due_datetime.strftime('%Y-%m-%d %H:%M')
            
            priority = task.get('priority', 1)
            priority_marker = "🔴" if priority == 4 else "🟠" if priority == 3 else "🟡" if priority == 2 else "⚪"
            
            task_list.append(f"{priority_marker} {task['content']} (마감: {due_str})")
        
        return "\n".join(task_list)
    
    except Exception as e:
        logger.error(f"Todoist 작업 목록 조회 중 오류 발생: {e}")
        return f"Todoist 정보를 가져오는 중 오류가 발생했습니다: {str(e)}"

# 기상청 동네예보 좌표
WEATHER_LOCATIONS = {
    "경상남도 창원시 성산구": {"nx": 91, "ny": 77},  # 창원시 성산구 좌표
    "서울특별시 강남구": {"nx": 61, "ny": 126},      # 강남구 좌표
    "부산광역시 해운대구": {"nx": 99, "ny": 75},     # 해운대구 좌표
    "제주특별자치도 제주시": {"nx": 53, "ny": 38},   # 제주시 좌표
}

# 날씨 코드에 대한 설명
WEATHER_DESCRIPTION = {
    "맑음": "☀️ 맑음",
    "구름많음": "⛅ 구름많음",
    "흐림": "☁️ 흐림",
    "비": "🌧️ 비",
    "비/눈": "🌨️ 비/눈",
    "눈": "❄️ 눈",
    "소나기": "🌦️ 소나기",
    "천둥번개": "⛈️ 천둥번개",
    "안개": "🌫️ 안개",
    "박무": "🌫️ 박무"
}

async def get_weather_forecast(location: str):
    try:
        # 기상청 API에 필요한 키가 설정되어 있는지 확인
        if not WEATHER_API_KEY:
            return "날씨 API 키가 설정되지 않았습니다. 관리자에게 문의하세요."
        
        # 위치 좌표 확인
        coords = WEATHER_LOCATIONS.get(location)
        if not coords:
            # 기본 위치로 대체
            default_location = "경상남도 창원시 성산구"
            coords = WEATHER_LOCATIONS.get(default_location)
            if not coords:
                return f"날씨 정보를 제공할 수 없는 지역입니다. 좌표 정보가 누락되었습니다."
            location = default_location
        
        # 현재 날짜와 시간 정보
        now = datetime.datetime.now(pytz.timezone('Asia/Seoul'))
        base_date = now.strftime("%Y%m%d")  # 오늘 날짜 YYYYMMDD 형식
        
        # 현재 시간에 따라 기준 시간 설정 (API 요구사항)
        # 더 간단히 고정 기준 시간 사용
        if now.hour < 6:
            base_time = "2300"
            # 전날 23시 데이터 사용
            base_date = (now - datetime.timedelta(days=1)).strftime("%Y%m%d")
        elif now.hour < 12:
            base_time = "0500"  # 오전에는 0500 데이터 사용
        elif now.hour < 18:
            base_time = "1100"  # 오후에는 1100 데이터 사용
        else:
            base_time = "1700"  # 밤에는 1700 데이터 사용
        
        logger.info(f"날씨 정보 요청: {location} (좌표: {coords}, 기준일시: {base_date} {base_time})")
        
        # 기상청 API 호출
        url = f"{WEATHER_API_URL}/getVilageFcst"
        params = {
            'serviceKey': WEATHER_API_KEY,
            'pageNo': '1',
            'numOfRows': '1000',
            'dataType': 'JSON',
            'base_date': base_date,
            'base_time': base_time,
            'nx': coords['nx'],
            'ny': coords['ny']
        }
        
        response = requests.get(url, params=params)
        
        if response.status_code != 200:
            logger.error(f"날씨 API 오류: {response.status_code}, {response.text}")
            return f"날씨 정보를 가져오는 중 오류가 발생했습니다. 상태 코드: {response.status_code}"
        
        # 응답 데이터 분석
        try:
            data = response.json()
            if 'response' not in data or 'header' not in data['response'] or 'body' not in data['response'] or data['response']['header']['resultCode'] != '00':
                logger.error(f"날씨 API 응답 구조 오류: {data}")
                return f"날씨 정보 응답 구조가 예상과 다릅니다."
            
            items = data['response']['body']['items']['item']
            
            # 날씨 정보 정리
            today_date = now.strftime("%Y%m%d")  # 오늘 날짜
            forecast_date = (now + datetime.timedelta(days=1)).strftime("%Y%m%d")  # 내일 날짜
            
            # 오늘과 내일의 데이터로 분류
            today_data = {}
            tomorrow_data = {}
            
            for item in items:
                if item['fcstDate'] == today_date:  # 오늘
                    if item['fcstTime'] not in today_data:
                        today_data[item['fcstTime']] = {}
                    today_data[item['fcstTime']][item['category']] = item['fcstValue']
                elif item['fcstDate'] == forecast_date:  # 내일
                    if item['fcstTime'] not in tomorrow_data:
                        tomorrow_data[item['fcstTime']] = {}
                    tomorrow_data[item['fcstTime']][item['category']] = item['fcstValue']
            
            # 결과 메시지 구성
            result = f"[{location} 날씨 정보]\n\n"
            
            # 오늘 날씨
            result += "🌡️ 오늘 날씨\n"
            # 현재 시간 이후의 시간대만 필터링
            current_hour = now.hour
            today_times = ["0900", "1200", "1500", "1800", "2100"]
            filtered_today_times = [t for t in today_times if int(t[:2]) > current_hour or (int(t[:2]) == current_hour and int(t[2:]) > now.minute)]
            
            # 오늘 날씨 데이터 처리
            if today_data and filtered_today_times:
                for time in filtered_today_times:
                    if time in today_data:
                        temp = today_data[time].get('TMP', '-')  # 기온
                        sky = today_data[time].get('SKY', '-')   # 하늘상태
                        pty = today_data[time].get('PTY', '0')   # 강수형태
                        pop = today_data[time].get('POP', '0')   # 강수확률
                        
                        # 하늘상태 변환
                        sky_text = "맑음" if sky == '1' else "구름많음" if sky == '3' else "흐림" if sky == '4' else "알 수 없음"
                        
                        # 강수형태 변환
                        if pty == '1':
                            weather_text = "비"
                        elif pty == '2':
                            weather_text = "비/눈"
                        elif pty == '3':
                            weather_text = "눈"
                        elif pty == '4':
                            weather_text = "소나기"
                        else:
                            weather_text = sky_text
                        
                        # 이모지 추가
                        weather_emoji = WEATHER_DESCRIPTION.get(weather_text, weather_text)
                        
                        time_formatted = f"{time[:2]}:{time[2:]}"
                        result += f"• {time_formatted}: {weather_emoji}, {temp}°C, 강수확률 {pop}%\n"
            else:
                result += "오늘 남은 시간의 날씨 정보가 없습니다.\n"
            
            # 내일 날씨
            result += "\n🌡️ 내일 날씨\n"
            tomorrow_times = ["0900", "1200", "1500", "1800", "2100"]  # 주요 시간대
            
            for time in tomorrow_times:
                if time in tomorrow_data:
                    temp = tomorrow_data[time].get('TMP', '-')  # 기온
                    sky = tomorrow_data[time].get('SKY', '-')   # 하늘상태
                    pty = tomorrow_data[time].get('PTY', '0')   # 강수형태
                    pop = tomorrow_data[time].get('POP', '0')   # 강수확률
                    
                    # 하늘상태 변환
                    sky_text = "맑음" if sky == '1' else "구름많음" if sky == '3' else "흐림" if sky == '4' else "알 수 없음"
                    
                    # 강수형태 변환
                    if pty == '1':
                        weather_text = "비"
                    elif pty == '2':
                        weather_text = "비/눈"
                    elif pty == '3':
                        weather_text = "눈"
                    elif pty == '4':
                        weather_text = "소나기"
                    else:
                        weather_text = sky_text
                    
                    # 이모지 추가
                    weather_emoji = WEATHER_DESCRIPTION.get(weather_text, weather_text)
                    
                    time_formatted = f"{time[:2]}:{time[2:]}"
                    result += f"• {time_formatted}: {weather_emoji}, {temp}°C, 강수확률 {pop}%\n"
            
            return result
            
        except Exception as e:
            logger.error(f"날씨 데이터 처리 중 오류 발생: {e}")
            return f"날씨 정보를 처리하는 중 오류가 발생했습니다: {str(e)}"
            
    except Exception as e:
        logger.error(f"날씨 정보 요청 중 오류 발생: {e}")
        return f"날씨 정보를 가져오는 중 오류가 발생했습니다: {str(e)}"

# --- 명령어 핸들러 함수들 ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE): # FR5.1
    user_name = update.effective_user.first_name
    await update.message.reply_text(
        f"안녕하세요, {user_name}님! jpgn_21_bot입니다.\n"
        f"팀의 일정과 할 일을 관리하고 날씨 정보를 알려드립니다.\n"
        f"사용 가능한 명령어는 /help 를 입력하여 확인하세요."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE): # FR5.2
    help_text = """
jpgn_21_bot 사용법 안내

정보 조회 (수동)
/today - 오늘 일정, 할 일, 날씨
/tomorrow - 내일 일정, 할 일, 날씨
/thisweek - 이번 주 일정 및 할 일
/nextweek - 다음 주 일정 및 할 일

매일 아침 08:00와 저녁 20:00에 자동으로 일정 브리핑이 제공됩니다.

문의사항은 관리자에게 연락해주세요.
"""
    await update.message.reply_text(help_text)

async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE): # FR5.8
    try:
        calendar_info = await get_google_calendar_events("오늘")
        todoist_info = await get_todoist_tasks("오늘")
        weather_info = await get_weather_forecast(DEFAULT_WEATHER_LOCATION)
        
        response_text = f"오늘의 정보\n\n"
        response_text += f"📅 구글 캘린더\n{calendar_info}\n\n"
        response_text += f"📝 Todoist\n{todoist_info}\n\n"
        response_text += f"🌦️ 날씨 ({DEFAULT_WEATHER_LOCATION})\n{weather_info}"
        
        await update.message.reply_text(response_text)
    except Exception as e:
        logger.error(f"오늘 명령어 처리 중 오류: {e}")
        await update.message.reply_text(f"정보를 가져오는 중 오류가 발생했습니다: {str(e)}")

async def tomorrow_command(update: Update, context: ContextTypes.DEFAULT_TYPE): # FR5.9
    try:
        calendar_info = await get_google_calendar_events("내일")
        todoist_info = await get_todoist_tasks("내일")
        # 내일 날씨는 보통 오늘의 날씨 정보에서 함께 제공되거나 별도 요청 필요
        weather_info = await get_weather_forecast(DEFAULT_WEATHER_LOCATION) # 일단 오늘 날씨로 대체, 추후 수정
        
        response_text = f"내일의 정보\n\n"
        response_text += f"📅 구글 캘린더\n{calendar_info}\n\n"
        response_text += f"📝 Todoist\n{todoist_info}\n\n"
        response_text += f"🌦️ 날씨 ({DEFAULT_WEATHER_LOCATION})\n{weather_info}" # 내일 날씨로 수정 필요
        
        await update.message.reply_text(response_text)
    except Exception as e:
        logger.error(f"내일 명령어 처리 중 오류: {e}")
        await update.message.reply_text(f"정보를 가져오는 중 오류가 발생했습니다: {str(e)}")

async def this_week_command(update: Update, context: ContextTypes.DEFAULT_TYPE): # FR5.10
    try:
        calendar_info = await get_google_calendar_events("이번주")
        todoist_info = await get_todoist_tasks("이번주")
        
        response_text = f"이번 주 정보\n\n"
        response_text += f"📅 구글 캘린더\n{calendar_info}\n\n"
        response_text += f"📝 Todoist\n{todoist_info}"
        
        await update.message.reply_text(response_text)
    except Exception as e:
        logger.error(f"이번주 명령어 처리 중 오류: {e}")
        await update.message.reply_text(f"정보를 가져오는 중 오류가 발생했습니다: {str(e)}")

async def next_week_command(update: Update, context: ContextTypes.DEFAULT_TYPE): # FR5.11
    try:
        calendar_info = await get_google_calendar_events("다음주")
        todoist_info = await get_todoist_tasks("다음주")
        
        response_text = f"다음 주 정보\n\n"
        response_text += f"📅 구글 캘린더\n{calendar_info}\n\n"
        response_text += f"📝 Todoist\n{todoist_info}"
        
        await update.message.reply_text(response_text)
    except Exception as e:
        logger.error(f"다음주 명령어 처리 중 오류: {e}")
        await update.message.reply_text(f"정보를 가져오는 중 오류가 발생했습니다: {str(e)}")

# --- 자동 알림 함수 (FR4) ---
async def morning_briefing(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    try:
        # 오늘의 정보 요약 생성
        calendar_info = await get_google_calendar_events("오늘")
        todoist_info = await get_todoist_tasks("오늘")
        weather_info = await get_weather_forecast(DEFAULT_WEATHER_LOCATION)
        
        briefing_text = f"[아침 브리핑] 오늘의 정보\n\n"
        briefing_text += f"📅 구글 캘린더\n{calendar_info}\n\n"
        briefing_text += f"📝 Todoist\n{todoist_info}\n\n"
        briefing_text += f"🌦️ 날씨 ({DEFAULT_WEATHER_LOCATION})\n{weather_info}"
        
        # 저장된 채팅 ID로 메시지 전송
        await context.bot.send_message(chat_id=job.chat_id, text=briefing_text)
        logger.info(f"아침 브리핑 전송 완료 (Chat ID: {job.chat_id})")
    except Exception as e:
        logger.error(f"아침 브리핑 생성 중 오류 발생: {e}")

async def evening_briefing(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    try:
        # 내일의 정보 요약 생성
        calendar_info = await get_google_calendar_events("내일")
        todoist_info = await get_todoist_tasks("내일")
        weather_info = await get_weather_forecast(DEFAULT_WEATHER_LOCATION)
        
        briefing_text = f"[저녁 브리핑] 내일의 정보\n\n"
        briefing_text += f"📅 구글 캘린더\n{calendar_info}\n\n"
        briefing_text += f"📝 Todoist\n{todoist_info}\n\n"
        briefing_text += f"🌦️ 날씨 ({DEFAULT_WEATHER_LOCATION})\n{weather_info}"
        
        # 저장된 채팅 ID로 메시지 전송
        await context.bot.send_message(chat_id=job.chat_id, text=briefing_text)
        logger.info(f"저녁 브리핑 전송 완료 (Chat ID: {job.chat_id})")
    except Exception as e:
        logger.error(f"저녁 브리핑 생성 중 오류 발생: {e}")

# 새로운 채팅방에 추가될 때 자동으로 채팅 ID 저장
async def new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    chat_id = update.effective_chat.id
    
    for member in update.message.new_chat_members:
        if member.id == bot.id:
            logger.info(f"봇이 새 채팅방에 추가됨: {chat_id}")
            
            # 이 채팅방에 아침, 저녁 브리핑 일정 추가
            add_briefing_schedule(context.job_queue, chat_id)
            
            await update.message.reply_text(
                "안녕하세요! jpgn_21_bot입니다.\n"
                "팀의 일정과 할 일을 관리하고 날씨 정보를 알려드립니다.\n"
                "매일 아침 08:00와 저녁 20:00에 자동으로 브리핑이 제공됩니다.\n"
                "사용 가능한 명령어는 /help 를 입력하여 확인하세요."
            )

# 브리핑 스케줄 설정 함수
def add_briefing_schedule(job_queue, chat_id):
    # 기존 일정이 있으면 제거
    current_jobs = job_queue.get_jobs_by_name(f"morning_briefing_{chat_id}")
    for job in current_jobs:
        job.schedule_removal()
    
    current_jobs = job_queue.get_jobs_by_name(f"evening_briefing_{chat_id}")
    for job in current_jobs:
        job.schedule_removal()
    
    # 한국 시간대 설정
    korea_tz = pytz.timezone('Asia/Seoul')
    
    # 아침 브리핑 (08:00)
    morning_time = datetime.time(hour=8, minute=0, tzinfo=korea_tz)
    job_queue.run_daily(
        morning_briefing, 
        time=morning_time, 
        chat_id=chat_id,
        name=f"morning_briefing_{chat_id}"
    )
    logger.info(f"아침 브리핑 일정 추가됨 (08:00, Chat ID: {chat_id})")
    
    # 저녁 브리핑 (20:00)
    evening_time = datetime.time(hour=20, minute=0, tzinfo=korea_tz)
    job_queue.run_daily(
        evening_briefing, 
        time=evening_time, 
        chat_id=chat_id,
        name=f"evening_briefing_{chat_id}"
    )
    logger.info(f"저녁 브리핑 일정 추가됨 (20:00, Chat ID: {chat_id})")

def main() -> None:
    """봇을 시작합니다."""
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # 명령어 핸들러 등록
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("today", today_command))
    application.add_handler(CommandHandler("tomorrow", tomorrow_command))
    application.add_handler(CommandHandler("thisweek", this_week_command))
    application.add_handler(CommandHandler("nextweek", next_week_command))
    
    # 새 채팅방에 추가될 때 이벤트 핸들러
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_chat_members))

    # 이미 작동 중인 채팅방에 대한 브리핑 설정
    # 실제 운영 시에는 DB에서 저장된 채팅 ID 목록을 불러와야 함
    # 여기서는 예시로 특정 채팅 ID 사용
    chat_ids = []
    if 'TELEGRAM_CHAT_IDS' in os.environ:
        chat_ids_str = os.environ.get('TELEGRAM_CHAT_IDS', '')
        if chat_ids_str:
            chat_ids = [int(chat_id.strip()) for chat_id in chat_ids_str.split(',') if chat_id.strip()]
    
    job_queue = application.job_queue
    for chat_id in chat_ids:
        add_briefing_schedule(job_queue, chat_id)

    logger.info("봇 시작 중...")
    application.run_polling()

if __name__ == '__main__':
    main() 