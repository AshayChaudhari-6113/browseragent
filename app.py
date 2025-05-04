import os
import asyncio
import platform
from io import StringIO
import contextlib
from datetime import datetime
from dotenv import load_dotenv
from browser_use import Agent
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContextConfig
from langchain_google_genai import ChatGoogleGenerativeAI
import streamlit as st
import httpx

# ——— Page configuration (must be first Streamlit command) ———
st.set_page_config(page_title='Browser Automation Chat', layout='wide')

# ——— Windows event loop policy ———
if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# ——— Load environment variables ———
load_dotenv()
if not os.getenv("GOOGLE_API_KEY"):
    raise EnvironmentError("Please set GOOGLE_API_KEY in your environment.")

# ——— Determine base Chrome User Data directory ———
env_dir = os.getenv('CHROME_USER_DATA_DIR')
if env_dir and os.path.isdir(env_dir):
    base_user_data = env_dir
else:
    if platform.system() == 'Windows':
        base_user_data = os.path.join(os.getenv('LOCALAPPDATA', ''), 'Google', 'Chrome', 'User Data')
    elif platform.system() == 'Darwin':
        base_user_data = os.path.expanduser('~/Library/Application Support/Google/Chrome')
    else:
        base_user_data = os.path.expanduser('~/.config/google-chrome')

# ——— List Chrome profiles ———
def get_profiles():
    try:
        profiles = [d for d in os.listdir(base_user_data) if os.path.isdir(os.path.join(base_user_data, d))]
        profiles.sort()
        return profiles
    except Exception:
        return ['Default']

# ——— Async helper to choose BrowserConfig: attach to running CDP if available ———
async def choose_browser_config(profile: str) -> BrowserConfig:
    # 1) Try CDP connect
    cdp_url = os.getenv('CDP_URL', 'http://localhost:9222')
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{cdp_url}/json/version", timeout=2)
            if resp.status_code == 200:
                # Attach to existing Chrome via CDP
                return BrowserConfig(cdp_url=cdp_url)
    except Exception:
        pass

    # 2) Fallback to launching Chrome binary with profile + flags
    chrome_path = os.getenv('CHROME_BINARY_PATH') or {
        'Windows': r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        'Darwin': '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        'Linux': '/usr/bin/google-chrome'
    }.get(platform.system())
    extra_args = [
        f"--user-data-dir={base_user_data}",
        f"--profile-directory={profile}",
        "--window-size=1920,1080",
    ]

    # **Add new_context_config here** to set the CSS viewport
    return BrowserConfig(
        browser_binary_path=chrome_path,
        headless=False,
        extra_browser_args=extra_args,
        new_context_config=BrowserContextConfig(
            browser_window_size={"width": 1920, "height": 1080}
        )
    )

# ——— Main execution: synchronous wrapper ———
def execute_task(task_input: str, profile: str) -> str:
    # Choose config (CDP or binary)
    config = asyncio.run(choose_browser_config(profile))
    browser = Browser(config=config)
    llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", temperature=0.0, max_retries=2)
    agent = Agent(task=task_input, llm=llm, browser=browser)
    # Capture logs
    buf = StringIO()
    with contextlib.redirect_stdout(buf):
        asyncio.run(agent.run(max_steps=100))
    asyncio.run(browser.close())
    # Return last 4 log lines
    lines = buf.getvalue().splitlines()
    return "\n".join(lines[-4:] if len(lines) >= 4 else lines)

# ——— Streamlit UI ———
st.title('💬 Browser Automation Chat')

# Profile selector (default to 'Default')
profiles = get_profiles()
def_index = profiles.index('Default') if 'Default' in profiles else 0
selected_profile = st.selectbox('Select Chrome Profile', profiles, index=def_index)

# Chat history
if 'messages' not in st.session_state:
    st.session_state['messages'] = []
for msg in st.session_state['messages']:
    st.chat_message(msg['role']).write(msg['content'])

# User input
user_input = st.chat_input('Describe the browser task...')
if user_input:
    # Append & show user message
    st.session_state['messages'].append({'role': 'user', 'content': user_input})
    st.chat_message('user').write(user_input)

    # Run agent and display logs
    with st.chat_message('assistant'):
        with st.spinner('Running agent...'):
            try:
                logs = execute_task(user_input, selected_profile)
                st.subheader('Agent Logs')
                st.code(logs)
                st.success('✅ Task completed successfully!')
                content = f"{logs}\n✅ Task completed successfully!"
                st.session_state['messages'].append({'role': 'assistant', 'content': content})
            except Exception as e:
                err = f"⚠️ Error: {e}"
                st.error(err)
                st.session_state['messages'].append({'role': 'assistant', 'content': err})

st.markdown('---')
st.write(f"Using Chrome profile: {selected_profile}")
