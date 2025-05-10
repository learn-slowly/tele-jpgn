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
    
    # 날짜 설정 및 필터 구성
    if date_type == "오늘":
        if TODOIST_PROJECT_ID:
            filter_param = f"today & project_id:{TODOIST_PROJECT_ID}"
        else:
            filter_param = "today"
        title = "오늘"
    elif date_type == "내일":
        if TODOIST_PROJECT_ID:
            filter_param = f"tomorrow & project_id:{TODOIST_PROJECT_ID}"
        else:
            filter_param = "tomorrow"
        title = "내일"
    elif date_type == "이번주":
        # 주간 필터는 문법이 복잡해서 다른 방식으로 처리
        end_date = (now + datetime.timedelta(days=7)).strftime("%Y-%m-%d")
        if TODOIST_PROJECT_ID:
            filter_param = f"(due:today | due:>today due:before {end_date}) & project_id:{TODOIST_PROJECT_ID}"
        else:
            filter_param = f"due:today | due:>today due:before {end_date}"
        title = "이번 주"
    elif date_type == "다음주":
        next_week_start = now + datetime.timedelta(days=7-now.weekday())
        next_week_end = next_week_start + datetime.timedelta(days=6)
        if TODOIST_PROJECT_ID:
            filter_param = f"(due:>={next_week_start.strftime('%Y-%m-%d')} & due:<={next_week_end.strftime('%Y-%m-%d')}) & project_id:{TODOIST_PROJECT_ID}"
        else:
            filter_param = f"due:>={next_week_start.strftime('%Y-%m-%d')} & due:<={next_week_end.strftime('%Y-%m-%d')}"
        title = "다음 주"
    else:
        return "알 수 없는 기간입니다."
    
    try:
        logger.info(f"Todoist 작업 정보 요청: {date_type} (필터: {filter_param})")
        
        # Todoist API를 호출하여 작업 목록 가져오기
        response = requests.get(
            f"{TODOIST_API_URL}",
            headers=headers,
            params={"filter": filter_param}
        )
        
        if response.status_code != 200:
            logger.error(f"Todoist API 오류: {response.status_code}, {response.text}")
            return f"Todoist API 요청 중 오류가 발생했습니다. 상태 코드: {response.status_code}"
        
        tasks = response.json()
        
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

async def get_weather_forecast(location: str):
    # TODO: 날씨 API 연동 로직 구현 (FR3)
    logger.info(f"날씨 정보 요청: {location}")
    return f"[임시] {location}의 날씨 정보입니다."

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