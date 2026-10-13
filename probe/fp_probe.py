import os, json, psycopg2
conn = psycopg2.connect(os.environ['TGSTACK_DSN']); conn.autocommit = True
cur = conn.cursor()
cur.execute("SELECT id, group_tag, fp_model, fp_sys, fp_app FROM tg_accounts WHERE fp_model ILIKE %s AND deleted_at='' AND status=1 ORDER BY id LIMIT 5", ('iPhone%',))
rows = cur.fetchall()
print('APPLE-CONTAINERS:', [(r[0], (r[1] or '')[:10], r[2], r[3], r[4]) for r in rows], flush=True)
if not rows: raise SystemExit('no apple-container account')
aid = rows[0][0]
cur.execute("SELECT line FROM import_items WHERE account_id=%s AND ok=1 ORDER BY id DESC LIMIT 1", (aid,))
row = cur.fetchone()
if not row: raise SystemExit('no session line')
ss = row[0].strip()
if ss[0] == '1' and '=' not in ss:
    ss = ss + '=' * ((-(len(ss) - 1)) % 4)
print('SS-OK len', len(ss), flush=True)
from telethon import TelegramClient, functions
from telethon.sessions import StringSession
client = TelegramClient(StringSession(ss), 2040, 'b18441a1ff607e10a989891a5462e627')
import asyncio
async def main():
    await client.connect()
    if not await client.is_user_authorized():
        print('NOT-AUTH', flush=True); return
    auths = await client(functions.account.GetAuthorizationsRequest())
    for a in auths.authorizations:
        print('AUTH|', a.device_model, '|', a.platform, '|', a.system_version, '|api_id', a.api_id, '|', a.app_name, '|', a.app_version, flush=True)
    await client.disconnect()
asyncio.get_event_loop().run_until_complete(main())
