import discord
from discord import app_commands
from discord.ext import commands
import os,sys,asyncio,json,re,time
from datetime import datetime,timedelta
from dotenv import load_dotenv
from aiohttp import web

# ---- LOGS ----
os.makedirs("logs",exist_ok=True)
def eL(x): open("logs/errors.log","a",encoding="utf-8").write(f"[{datetime.utcnow().isoformat()}] {type(x).__name__}: {x}\n")
load_dotenv()

T=os.getenv('DISCORD_TOKEN')
O=int(os.getenv('OWNER_ID',0))
L=int(os.getenv('LOG_CHANNEL_ID',0))
P=1529248455157874879
G=1528337219612311633
PORT=int(os.getenv('PORT',8080))

if not T or T.strip()=='':
    print("❌");sys.exit(1)
if not all([T,O,L]): print("❌");sys.exit(1)

# ---- DATA ----
def lw():
    if os.path.exists("data/warnings.json"):
        with open("data/warnings.json","r") as f: return json.load(f)
    return {}
def sw(x):
    with open("data/warnings.json","w") as f: json.dump(x,f,indent=2)
def lb():
    if os.path.exists("data/blacklist.json"):
        with open("data/blacklist.json","r") as f: return json.load(f)
    return []
def sb(x):
    with open("data/blacklist.json","w") as f: json.dump(x,f,indent=2)

# ---- BOT ----
intents=discord.Intents.default()
intents.message_content=True
intents.members=True
b=commands.Bot(command_prefix='!',intents=intents)

# ---- Роли с доступом ----
ALLOWED_ROLES = [
    1529251785678655589,
    1529252048883810485,
    1529253808666841302
]

# ---- Защита от спама наказаниями ----
mod_actions = {}
mod_lock = asyncio.Lock()

async def check_mod_rate(i):
    now=time.time()
    uid=i.user.id
    async with mod_lock:
        if uid not in mod_actions: mod_actions[uid]=[]
        mod_actions[uid]=[t for t in mod_actions[uid] if now-t<60]
        if len(mod_actions[uid])>=5:
            try:
                await i.user.timeout(timedelta(hours=10), reason="Превышение лимита наказаний (5 за минуту)")
                await i.followup.send("⚠️ Вы превысили лимит наказаний (5 за минуту). Тайм-аут 10 часов.", ephemeral=True)
                ch=b.get_channel(L)
                if ch:
                    e=discord.Embed(title="⛔ Авто-тайм-аут модератора", color=discord.Color.red())
                    e.add_field(name="Модератор", value=i.user.mention)
                    e.add_field(name="Причина", value="5 наказаний за минуту")
                    e.add_field(name="Длительность", value="10 часов")
                    await ch.send(embed=e)
            except Exception as e: eL(e)
            return False
        mod_actions[uid].append(now)
        return True

# ---- Проверка прав (с исключением для пользователя 689818377803399219) ----
BANNED_USER_ID = 689818377803399219

def has_allowed_role(i):
    # Запрещаем конкретному пользователю
    if i.user.id == BANNED_USER_ID:
        return False
    # Владелец всегда имеет доступ
    if i.user.id == O:
        return True
    # Проверяем роли
    for role_id in ALLOWED_ROLES:
        role = i.guild.get_role(role_id)
        if role and role in i.user.roles:
            return True
    return False

def pd(ds):
    p=re.compile(r'(\d+)([dhms])')
    m=p.findall(ds.lower())
    if not m: return 0
    s=0
    for v,u in m:
        v=int(v)
        if u=='d': s+=v*86400
        elif u=='h': s+=v*3600
        elif u=='m': s+=v*60
        elif u=='s': s+=v
    return s

async def spn(a,target,mod,reason=None,duration=None):
    ch=b.get_channel(P)
    if not ch: return
    msg=f"**{a}** | {target.mention} | {mod.mention}"
    if reason: msg+=f" | Причина: {reason}"
    if duration: msg+=f" | Длительность: {duration}"
    try: await ch.send(msg)
    except: pass

async def la(i,a,target=None,reason=None,extra=None):
    ch=b.get_channel(L)
    if not ch: return
    e=discord.Embed(title=f"📋 {a}",color=discord.Color.blue(),timestamp=datetime.utcnow())
    e.add_field(name="Модератор",value=discord.utils.escape_mentions(i.user.mention),inline=False)
    if target: e.add_field(name="Цель",value=discord.utils.escape_mentions(f"{target.mention} ({target.id})"),inline=False)
    if reason: e.add_field(name="Причина",value=discord.utils.escape_mentions(reason),inline=False)
    if extra: e.add_field(name="Дополнительно",value=discord.utils.escape_mentions(extra),inline=False)
    e.set_footer(text=f"ID: {i.user.id}")
    try: await ch.send(embed=e)
    except: pass

# ---- COG ----
class MC(commands.Cog):
    def __init__(self, b): self.b=b

    async def cog_check(self, i):
        if str(i.user.id) in lb():
            await i.response.send_message("⛔",ephemeral=True); return False
        if not has_allowed_role(i):
            await i.response.send_message("⛔ У вас нет прав.",ephemeral=True); return False
        return True

    # ---- Все команды (без изменений) ----
    @app_commands.command(name="ban")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(member="Пользователь",reason="Причина",delete_days="Удалить за N дней (0-7)")
    async def bn(self,i,member:discord.Member,reason:str="Не указана",delete_days:int=0):
        if member.top_role>=i.user.top_role:
            await i.response.send_message("❌",ephemeral=True); return
        if not await check_mod_rate(i): return
        await i.response.defer(ephemeral=True)
        try:
            await member.ban(reason=f"{i.user}: {reason}",delete_message_days=delete_days)
            await i.followup.send(f"✅ {member.mention} забанен.",ephemeral=True)
            await la(i,"Бан",target=member,reason=reason,extra=f"Удалено за {delete_days} дн.")
            await spn("Бан",member,i.user,reason)
        except Exception as e: await i.followup.send(f"❌ {e}",ephemeral=True); eL(e)

    @app_commands.command(name="tempban")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(member="Пользователь",duration="1d,2h,30m",reason="Причина")
    async def tb(self,i,member:discord.Member,duration:str,reason:str="Не указана"):
        if member.top_role>=i.user.top_role:
            await i.response.send_message("❌",ephemeral=True); return
        s=pd(duration)
        if s<=0:
            await i.response.send_message("❌",ephemeral=True); return
        if not await check_mod_rate(i): return
        await i.response.defer(ephemeral=True)
        try:
            await member.ban(reason=f"{i.user}: {reason} (на {duration})")
            await i.followup.send(f"✅ {member.mention} на {duration}",ephemeral=True)
            await la(i,"Временный бан",target=member,reason=reason,extra=f"Длительность: {duration}")
            await spn("Временный бан",member,i.user,reason,duration)
            async def _():
                await asyncio.sleep(s)
                try: await member.unban(reason="Авторазбан")
                except: pass
            asyncio.create_task(_())
        except Exception as e: await i.followup.send(f"❌ {e}",ephemeral=True); eL(e)

    @app_commands.command(name="kick")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(member="Пользователь",reason="Причина")
    async def k(self,i,member:discord.Member,reason:str="Не указана"):
        if member.top_role>=i.user.top_role:
            await i.response.send_message("❌",ephemeral=True); return
        if not await check_mod_rate(i): return
        await i.response.defer(ephemeral=True)
        try:
            await member.kick(reason=f"{i.user}: {reason}")
            await i.followup.send(f"✅ {member.mention} кикнут.",ephemeral=True)
            await la(i,"Кик",target=member,reason=reason)
            await spn("Кик",member,i.user,reason)
        except Exception as e: await i.followup.send(f"❌ {e}",ephemeral=True); eL(e)

    @app_commands.command(name="mute")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(member="Пользователь",duration="Минуты",reason="Причина")
    async def m(self,i,member:discord.Member,duration:int=60,reason:str="Не указана"):
        if member.top_role>=i.user.top_role:
            await i.response.send_message("❌",ephemeral=True); return
        if duration>40320:
            await i.response.send_message("❌",ephemeral=True); return
        if not await check_mod_rate(i): return
        await i.response.defer(ephemeral=True)
        try:
            await member.timeout(timedelta(minutes=duration),reason=f"{i.user}: {reason}")
            await i.followup.send(f"✅ {member.mention} на {duration} мин.",ephemeral=True)
            await la(i,"Мут",target=member,reason=reason,extra=f"{duration} мин.")
            await spn("Мут",member,i.user,reason,f"{duration} мин.")
        except Exception as e: await i.followup.send(f"❌ {e}",ephemeral=True); eL(e)

    @app_commands.command(name="tempmute")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(member="Пользователь",duration="1d,2h,30m",reason="Причина")
    async def tm(self,i,member:discord.Member,duration:str,reason:str="Не указана"):
        s=pd(duration)
        if s<=0:
            await i.response.send_message("❌",ephemeral=True); return
        if s>40320*60:
            await i.response.send_message("❌",ephemeral=True); return
        if member.top_role>=i.user.top_role:
            await i.response.send_message("❌",ephemeral=True); return
        if not await check_mod_rate(i): return
        await i.response.defer(ephemeral=True)
        try:
            await member.timeout(timedelta(seconds=s),reason=f"{i.user}: {reason}")
            await i.followup.send(f"✅ {member.mention} на {duration}",ephemeral=True)
            await la(i,"Временный мут",target=member,reason=reason,extra=f"Длительность: {duration}")
            await spn("Временный мут",member,i.user,reason,duration)
        except Exception as e: await i.followup.send(f"❌ {e}",ephemeral=True); eL(e)

    @app_commands.command(name="unmute")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(member="Пользователь")
    async def um(self,i,member:discord.Member):
        if member.top_role>=i.user.top_role:
            await i.response.send_message("❌",ephemeral=True); return
        await i.response.defer(ephemeral=True)
        try:
            await member.timeout(None)
            await i.followup.send(f"✅ Мут снят с {member.mention}.",ephemeral=True)
            await la(i,"Снятие мута",target=member)
        except Exception as e: await i.followup.send(f"❌ {e}",ephemeral=True); eL(e)

    @app_commands.command(name="clear")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(amount="1-100")
    async def cl(self,i,amount:int=10):
        if amount<1 or amount>100:
            await i.response.send_message("❌",ephemeral=True); return
        await i.response.defer(ephemeral=True)
        try:
            d=await i.channel.purge(limit=amount)
            await i.followup.send(f"✅ Удалено {len(d)}.",ephemeral=True)
            await la(i,"Очистка чата",extra=f"Удалено {len(d)}")
        except Exception as e: await i.followup.send(f"❌ {e}",ephemeral=True); eL(e)

    @app_commands.command(name="warn")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(member="Пользователь",reason="Причина")
    async def w(self,i,member:discord.Member,reason:str="Не указана"):
        if member.top_role>=i.user.top_role:
            await i.response.send_message("❌",ephemeral=True); return
        if not await check_mod_rate(i): return
        await i.response.defer(ephemeral=True)
        w=lw()
        uid=str(member.id)
        if uid not in w: w[uid]=[]
        w[uid].append({"moderator":str(i.user.id),"reason":reason,"timestamp":datetime.utcnow().isoformat()})
        sw(w)
        await i.followup.send(f"✅ {member.mention} получил предупреждение. Всего: {len(w[uid])}",ephemeral=True)
        await la(i,"Предупреждение",target=member,reason=reason)
        await spn("Предупреждение",member,i.user,reason)

    @app_commands.command(name="warnings")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(member="Пользователь")
    async def ws(self,i,member:discord.Member):
        w=lw()
        uid=str(member.id)
        if uid not in w or not w[uid]:
            await i.response.send_message(f"У {member.mention} нет предупреждений.",ephemeral=True); return
        await i.response.defer(ephemeral=True)
        e=discord.Embed(title=f"Предупреждения {member.display_name}",color=discord.Color.orange())
        for n,wn in enumerate(w[uid],1):
            mod=i.guild.get_member(int(wn['moderator']))
            mn=mod.display_name if mod else wn['moderator']
            e.add_field(name=f"#{n}",value=f"Модератор: {mn}\nПричина: {wn['reason']}\nДата: {wn['timestamp']}",inline=False)
        await i.followup.send(embed=e,ephemeral=True)

    @app_commands.command(name="clearwarns")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(member="Пользователь")
    async def cw(self,i,member:discord.Member):
        if member.top_role>=i.user.top_role:
            await i.response.send_message("❌",ephemeral=True); return
        await i.response.defer(ephemeral=True)
        w=lw()
        uid=str(member.id)
        if uid in w:
            del w[uid]; sw(w)
            await i.followup.send(f"✅ Предупреждения для {member.mention} очищены.",ephemeral=True)
            await la(i,"Очистка предупреждений",target=member)
        else:
            await i.followup.send(f"У {member.mention} нет предупреждений.",ephemeral=True)

    @app_commands.command(name="unban")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(user_id="ID пользователя",reason="Причина")
    async def ub(self,i,user_id:str,reason:str="Не указана"):
        await i.response.defer(ephemeral=True)
        try:
            u=discord.Object(id=int(user_id))
            await i.guild.unban(u,reason=f"{i.user}: {reason}")
            await i.followup.send(f"✅ Пользователь {user_id} разбанен.",ephemeral=True)
            await la(i,"Разбан",extra=f"ID: {user_id}")
        except Exception as e: await i.followup.send(f"❌ {e}",ephemeral=True); eL(e)

    @app_commands.command(name="blacklist")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(user="Пользователь", action="add или remove")
    async def bl(self,i,user:discord.User,action:str):
        if i.user.id!=O:
            await i.response.send_message("❌ Только владелец.",ephemeral=True); return
        await i.response.defer(ephemeral=True)
        bl=lb()
        uid=str(user.id)
        if action.lower()=="add":
            if uid not in bl:
                bl.append(uid); sb(bl)
                await i.followup.send(f"✅ {user.mention} добавлен в чёрный список.",ephemeral=True)
                await la(i,"Добавлен в чёрный список",target=user)
            else:
                await i.followup.send(f"⚠️ {user.mention} уже в чёрном списке.",ephemeral=True)
        elif action.lower()=="remove":
            if uid in bl:
                bl.remove(uid); sb(bl)
                await i.followup.send(f"✅ {user.mention} удалён из чёрного списка.",ephemeral=True)
                await la(i,"Удалён из чёрного списка",target=user)
            else:
                await i.followup.send(f"⚠️ {user.mention} не в чёрном списке.",ephemeral=True)
        else:
            await i.followup.send("❌ Используйте add или remove.",ephemeral=True)

# ---- WEB ----
async def health(req):
    return web.Response(text="OK",status=200)
async def webstart():
    app=web.Application()
    app.router.add_get('/', health)
    app.router.add_get('/health', health)
    runner=web.AppRunner(app)
    await runner.setup()
    site=web.TCPSite(runner, host='0.0.0.0', port=PORT)
    await site.start()
    print(f"🌐 Health check на порту {PORT}")
    await asyncio.Event().wait()

@b.event
async def on_ready():
    print(f'✅ {b.user}')
    try:
        g=discord.Object(id=G)
        s=await b.tree.sync(guild=g)
        print(f"🔄 Синхронизировано {len(s)} команд")
    except Exception as e:
        print(f"⚠️ Ошибка синхронизации: {e}")

async def main():
    await b.add_cog(MC(b))
    asyncio.create_task(webstart())
    await b.start(T)

if __name__=="__main__":
    asyncio.run(main())
