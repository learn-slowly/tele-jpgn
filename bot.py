import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
import os # 추가
import datetime
import pytz
from google.oauth2 import service_account
from googleapiclient.discovery import build

# PRD에서 가져온 API 키 및 설정값 (Heroku Config Vars 사용 권장)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TODOIST_API_URL = "https://api.todoist.com/rest/v2/tasks" # 이 값은 환경 변수로 할 필요는 없을 수 있습니다.
TODOIST_API_TOKEN = os.environ.get("TODOIST_API_TOKEN")
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
    # TODO: Todoist API 연동 로직 구현 (FR2)
    logger.info(f"Todoist 작업 정보 요청: {date_type}")
    if date_type == "오늘":
        return f"[임시] 오늘의 Todoist 작업 목록입니다."
    elif date_type == "내일":
        return f"[임시] 내일의 Todoist 작업 목록입니다."
    elif date_type == "이번주":
        return f"[임시] 이번 주 Todoist 작업 목록입니다."
    elif date_type == "다음주":
        return f"[임시] 다음 주 Todoist 작업 목록입니다."
    return "알 수 없는 기간입니다."

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
    **jpgn_21_bot 사용법 안내**

    **정보 조회 (수동)**
    /today - 오늘 일정, 할 일, 날씨
    /tomorrow - 내일 일정, 할 일, 날씨
    /thisweek - 이번 주 일정 및 할 일
    /nextweek - 다음 주 일정 및 할 일

    **자동 알림 설정**
    /set_morning_briefing_time HH:MM - 아침 브리핑 시간 설정 (예: /set_morning_briefing_time 08:00)
    /set_evening_briefing_time HH:MM - 저녁 브리핑 시간 설정 (예: /set_evening_briefing_time 19:00)

    **연동 및 기타 설정**
    /connect_google_calendar - 구글 캘린더 연동 (구현 예정)
    /connect_todoist_project - Todoist 프로젝트 연동 (구현 예정)
    /set_weather_location [지역명] - 날씨 조회 지역 설정 (예: /set_weather_location 서울특별시 강남구)

    문의사항은 관리자에게 연락해주세요.
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def connect_google_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE): # FR5.3
    # TODO: OAuth2.0 연동 프로세스 구현 필요
    await update.message.reply_text("구글 캘린더 연동 기능은 현재 준비 중입니다. (대상 캘린더 ID: {})".format(GOOGLE_CALENDAR_ID))

async def connect_todoist_project(update: Update, context: ContextTypes.DEFAULT_TYPE): # FR5.4
    # TODO: Todoist API 연동 확인 로직 (토큰 유효성 등)
    await update.message.reply_text("Todoist 연동 기능은 현재 준비 중입니다. (대상 프로젝트: {})".format("PRD에 명시된 URL의 프로젝트")) # URL 직접 노출보다 설명으로 대체

async def set_weather_location(update: Update, context: ContextTypes.DEFAULT_TYPE): # FR5.5
    global DEFAULT_WEATHER_LOCATION # 실제 운영 시에는 DB나 파일에 사용자별/팀별 설정을 저장해야 함
    try:
        location = " ".join(context.args)
        if not location:
            await update.message.reply_text("지역명을 입력해주세요. 예: /set_weather_location 서울특별시 강남구")
            return
        DEFAULT_WEATHER_LOCATION = location
        await update.message.reply_text(f"기본 날씨 조회 지역이 '{location}'으로 설정되었습니다.")
        logger.info(f"날씨 지역 변경: {location}")
    except (IndexError, ValueError):
        await update.message.reply_text("사용법: /set_weather_location [지역명]")

async def set_morning_briefing_time(update: Update, context: ContextTypes.DEFAULT_TYPE): # FR5.6
    # TODO: 알림 시간 설정 로직 및 스케줄러 연동 (apscheduler 등)
    try:
        time_str = context.args[0]
        # 간단한 시간 형식 검증 (HH:MM) - 실제로는 더 엄밀한 검증 필요
        if len(time_str) == 5 and time_str[2] == ':':
            # context.job_queue.run_daily(...) 등으로 스케줄링
            await update.message.reply_text(f"아침 브리핑 시간이 '{time_str}'으로 설정되었습니다. (스케줄링 기능 구현 필요)")
            logger.info(f"아침 브리핑 시간 설정: {time_str}")
        else:
            raise ValueError
    except (IndexError, ValueError):
        await update.message.reply_text("사용법: /set_morning_briefing_time HH:MM (예: 08:00)")


async def set_evening_briefing_time(update: Update, context: ContextTypes.DEFAULT_TYPE): # FR5.7
    # TODO: 알림 시간 설정 로직 및 스케줄러 연동
    try:
        time_str = context.args[0]
        if len(time_str) == 5 and time_str[2] == ':':
            await update.message.reply_text(f"저녁 브리핑 시간이 '{time_str}'으로 설정되었습니다. (스케줄링 기능 구현 필요)")
            logger.info(f"저녁 브리핑 시간 설정: {time_str}")
        else:
            raise ValueError
    except (IndexError, ValueError):
        await update.message.reply_text("사용법: /set_evening_briefing_time HH:MM (예: 19:00)")

async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE): # FR5.8
    calendar_info = await get_google_calendar_events("오늘")
    todoist_info = await get_todoist_tasks("오늘")
    weather_info = await get_weather_forecast(DEFAULT_WEATHER_LOCATION)
    
    response_text = f"--- **오늘의 정보** ---\n\n"
    response_text += f"📅 **구글 캘린더**\n{calendar_info}\n\n"
    response_text += f"📝 **Todoist**\n{todoist_info}\n\n"
    response_text += f"🌦️ **날씨 ({DEFAULT_WEATHER_LOCATION})**\n{weather_info}"
    
    await update.message.reply_text(response_text, parse_mode='Markdown')

async def tomorrow_command(update: Update, context: ContextTypes.DEFAULT_TYPE): # FR5.9
    calendar_info = await get_google_calendar_events("내일")
    todoist_info = await get_todoist_tasks("내일")
    # 내일 날씨는 보통 오늘의 날씨 정보에서 함께 제공되거나 별도 요청 필요
    weather_info = await get_weather_forecast(DEFAULT_WEATHER_LOCATION) # 일단 오늘 날씨로 대체, 추후 수정
    
    response_text = f"--- **내일의 정보** ---\n\n"
    response_text += f"📅 **구글 캘린더**\n{calendar_info}\n\n"
    response_text += f"📝 **Todoist**\n{todoist_info}\n\n"
    response_text += f"🌦️ **날씨 ({DEFAULT_WEATHER_LOCATION})**\n{weather_info}" # 내일 날씨로 수정 필요
    
    await update.message.reply_text(response_text, parse_mode='Markdown')

async def this_week_command(update: Update, context: ContextTypes.DEFAULT_TYPE): # FR5.10
    calendar_info = await get_google_calendar_events("이번주")
    todoist_info = await get_todoist_tasks("이번주")
    
    response_text = f"--- **이번 주 정보** ---\n\n"
    response_text += f"📅 **구글 캘린더**\n{calendar_info}\n\n"
    response_text += f"📝 **Todoist**\n{todoist_info}"
    
    await update.message.reply_text(response_text, parse_mode='Markdown')

async def next_week_command(update: Update, context: ContextTypes.DEFAULT_TYPE): # FR5.11
    calendar_info = await get_google_calendar_events("다음주")
    todoist_info = await get_todoist_tasks("다음주")
    
    response_text = f"--- **다음 주 정보** ---\n\n"
    response_text += f"📅 **구글 캘린더**\n{calendar_info}\n\n"
    response_text += f"📝 **Todoist**\n{todoist_info}"
    
    await update.message.reply_text(response_text, parse_mode='Markdown')

# --- 자동 알림 함수 (FR4) ---
async def morning_briefing(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    # TODO: 실제 브리핑 내용 생성 로직 (오늘의 정보 요약)
    # 특정 chat_id로 메시지 보내기 (봇을 사용하는 그룹/사용자 ID를 알아야 함)
    # 이 부분은 사용자가 봇과 상호작용한 후 chat_id를 저장하는 로직이 필요합니다.
    # 여기서는 임시로 logger에만 출력합니다.
    logger.info(f"아침 브리핑 실행 시간입니다. (Chat ID: {job.chat_id if job else 'N/A'})")
    # await context.bot.send_message(chat_id=job.chat_id, text="굿모닝! 오늘의 브리핑입니다...")

async def evening_briefing(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    logger.info(f"저녁 브리핑 실행 시간입니다. (Chat ID: {job.chat_id if job else 'N/A'})")
    # await context.bot.send_message(chat_id=job.chat_id, text="오늘 하루도 수고하셨습니다! 내일 일정 브리핑입니다...")

def main() -> None:
    """봇을 시작합니다."""
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # 명령어 핸들러 등록
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("connect_google_calendar", connect_google_calendar))
    application.add_handler(CommandHandler("connect_todoist_project", connect_todoist_project))
    application.add_handler(CommandHandler("set_weather_location", set_weather_location))
    application.add_handler(CommandHandler("set_morning_briefing_time", set_morning_briefing_time))
    application.add_handler(CommandHandler("set_evening_briefing_time", set_evening_briefing_time))
    application.add_handler(CommandHandler("today", today_command))
    application.add_handler(CommandHandler("tomorrow", tomorrow_command))
    application.add_handler(CommandHandler("thisweek", this_week_command))
    application.add_handler(CommandHandler("nextweek", next_week_command))

    # 자동 알림 (Job Queue 사용 예시 - 실제 구현 시 chat_id 관리 및 정확한 시간 설정 필요)
    # job_queue = application.job_queue
    # job_queue.run_daily(morning_briefing, time=datetime.time(hour=8, minute=0, tzinfo=pytz.timezone('Asia/Seoul')), chat_id=TARGET_CHAT_ID) # TARGET_CHAT_ID 설정 필요
    # job_queue.run_daily(evening_briefing, time=datetime.time(hour=21, minute=0, tzinfo=pytz.timezone('Asia/Seoul')), chat_id=TARGET_CHAT_ID)

    logger.info("봇 시작 중...")
    application.run_polling()

if __name__ == '__main__':
    main() 