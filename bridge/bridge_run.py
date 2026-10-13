# -*- coding: utf-8 -*-
# Por Bark push bridge: Telethon listener -> Bark push -> tap opens Telegram Por
# Modes: listen (default) / login (auto when session invalid + TG_PHONE present)
import os, sys, time, asyncio, traceback, urllib.request, urllib.parse

RAW_CMD = os.environ.get('CMD_BASE', 'https://raw.githubusercontent.com/chaofanchacha-blip/tg-por-bridge/main/cmd')
API_ID = int(os.environ.get('TG_API_ID', '2040'))
API_HASH = os.environ.get('TG_API_HASH', 'b18441a1ff607e10a7c3f7d43981759c')
BARK_KEY = os.environ.get('BARK_KEY', '').strip()
PHONE = os.environ.get('TG_PHONE', '').strip()
SESSION_FILE = os.environ.get('SESSION_FILE', 'bridge/session.session')
LISTEN_MIN = int(os.environ.get('LISTEN_MINUTES', '320'))
BACKLOG_GRACE_SEC = 180  # skip pushes for updates older than this at startup


def log(*a):
    print(*a, flush=True)


def bark_push(title, body, url=None):
    if not BARK_KEY:
        log('BARK_NO_KEY')
        return
    q = {'group': 'por', 'level': 'timeSensitive', 'sound': 'calypso'}
    if url:
        q['url'] = url
    u = 'https://api.day.app/%s/%s/%s?%s' % (
        BARK_KEY,
        urllib.parse.quote(str(title)[:64]),
        urllib.parse.quote(str(body)[:240]),
        urllib.parse.urlencode(q),
    )
    try:
        with urllib.request.urlopen(u, timeout=20) as r:
            r.read()
    except Exception as e:
        log('BARK_ERR', repr(e)[:120])


def read_remote(name):
    try:
        with urllib.request.urlopen(RAW_CMD + '/' + name, timeout=15) as r:
            return r.read().decode('utf-8', 'replace').strip()
    except Exception:
        return ''


async def poll_remote(name, timeout_sec=300, interval=5):
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        v = read_remote(name)
        if v:
            return v
        await asyncio.sleep(interval)
    return ''


async def periodic(fn, sec):
    while True:
        await asyncio.sleep(sec)
        try:
            await fn()
        except Exception:
            traceback.print_exc()


def message_body(m):
    try:
        if m.photo:
            return '[图片]' + (' ' + m.message[:80] if m.message else '')
        if m.video_note:
            return '[视频留言]'
        if m.video:
            return '[视频]' + (' ' + m.message[:80] if m.message else '')
        if m.voice:
            return '[语音]'
        if m.sticker:
            return '[贴纸] ' + (getattr(m.sticker, 'alt', '') or '')
        if getattr(m, 'poll', None):
            return '[投票] ' + (m.poll.question or '')
        if getattr(m, 'contact', None):
            return '[联系人]'
        if getattr(m, 'geo', None):
            return '[位置]'
        if m.document:
            nm = getattr(m.file, 'name', '') or ''
            return '[文件]' + (' ' + nm[:80])
        txt = m.raw_text or ''
        if not txt and getattr(m, 'dice', None):
            return '[骰子]'
        return txt[:200]
    except Exception:
        return (m.raw_text or '')[:200]


async def main():
    from telethon import TelegramClient, events
    from telethon.sessions import StringSession
    from telethon.errors import SessionPasswordNeededError

    sess_str = ''
    if os.path.exists(SESSION_FILE):
        sess_str = open(SESSION_FILE).read().strip()

    client = TelegramClient(
        StringSession(sess_str) if sess_str else StringSession(),
        API_ID, API_HASH,
    )
    await client.connect()

    if not await client.is_user_authorized():
        if not PHONE:
            log('NO_SESSION_NO_PHONE')
            bark_push('Por推送桥', '未登录且未设置TG_PHONE,请先用手机号登录')
            return
        log('LOGIN_START')
        await client.send_code_request(PHONE)
        bark_push('Por推送桥', '验证码已发到Telegram,请转告我')
        code = await poll_remote('code.txt', timeout_sec=300)
        if not code:
            log('CODE_TIMEOUT')
            return
        try:
            await client.sign_in(PHONE, code)
        except SessionPasswordNeededError:
            log('NEED_2FA')
            bark_push('Por推送桥', '需要两步验证密码')
            pw = await poll_remote('pw.txt', timeout_sec=600)
            if not pw:
                log('PW_TIMEOUT')
                return
            await client.sign_in(password=pw)
        log('LOGIN_OK')
        bark_push('Por推送桥', '登录成功,推送桥上线')

    # persist session immediately (never printed to logs)
    open(SESSION_FILE, 'w').write(client.session.save())

    me = await client.get_me()
    log('BRIDGE_READY user=', me.id)

    muted = set()

    async def refresh_muted():
        nonlocal muted
        new = set()
        now = time.time()
        async for d in client.iter_dialogs(limit=400):
            ns = getattr(d.dialog, 'notify_settings', None)
            mu = getattr(ns, 'mute_until', None)
            if mu and mu > now:
                new.add(d.id)
        muted = new
        log('MUTED_REFRESHED', len(muted))

    await refresh_muted()
    asyncio.get_event_loop().create_task(periodic(refresh_muted, 600))

    started = time.time()

    @client.on(events.NewMessage(incoming=True))
    async def on_msg(event):
        try:
            if event.chat_id in muted:
                return
            ts = event.message.date
            if ts and (time.time() - ts) > BACKLOG_GRACE_SEC:
                return  # stale backlog after reconnect, don't spam
            chat = await event.get_chat()
            sender = await event.get_sender()
            m = event.message
            title = getattr(chat, 'title', None)
            if not title:
                title = ' '.join(filter(None, [
                    getattr(sender, 'first_name', ''),
                    getattr(sender, 'last_name', ''),
                ])) or 'Telegram'
            body = message_body(m)
            if not body:
                return
            bark_push(title, body, url='tg://')
        except Exception:
            traceback.print_exc()

    log('LISTENING minutes=', LISTEN_MIN)
    try:
        await asyncio.wait_for(client.run_until_disconnected(), LISTEN_MIN * 60)
    except asyncio.TimeoutError:
        log('LISTEN_WINDOW_DONE')
    try:
        open(SESSION_FILE, 'w').write(client.session.save())
    except Exception:
        traceback.print_exc()
    await client.disconnect()


if __name__ == '__main__':
    asyncio.run(main())
