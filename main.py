import discord
from discord import app_commands
from discord.ext import commands
import os
import sys
import asyncio
import json
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv
from aiohttp import web

load_dotenv()

# ---------- Конфигурация ----------
TOKEN = os.getenv('DISCORD_TOKEN')
OWNER_ID = int(os.getenv('OWNER_ID', 0))
LOG_CHANNEL_ID = int(os.getenv('LOG_CHANNEL_ID', 0))
PUNISHMENT_CHANNEL_ID = 1529248455157874879  # канал для кратких уведомлений

if not TOKEN or TOKEN.strip() == '':
    print("❌ Ошибка: токен не задан или пуст. Проверьте .env файл.")
    sys.exit(1)
TOKEN = TOKEN.strip()

if not all([TOKEN, OWNER_ID, LOG_CHANNEL_ID]):
    print("❌ Ошибка: не заданы все переменные окружения.")
    print("Необходимы: DISCORD_TOKEN, OWNER_ID, LOG_CHANNEL_ID")
    sys.exit(1)

# ---------- Данные ----------
WARNINGS_FILE = "data/warnings.json"
os.makedirs("data", exist_ok=True)

def load_warnings():
    if os.path.exists(WARNINGS_FILE):
        with open(WARNINGS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_warnings(warnings):
    with open(WARNINGS_FILE, "w") as f:
        json.dump(warnings, f, indent=2)

# ---------- Бот ----------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

MOD_ROLE_ID = 0
active_timers = {}

# ---------- Вспомогательные функции ----------
def is_mod_or_owner(interaction: discord.Interaction) -> bool:
    if interaction.user.id == OWNER_ID:
        return True
    if MOD_ROLE_ID == 0:
        return False
    role = interaction.guild.get_role(MOD_ROLE_ID)
    if role and role in interaction.user.roles:
        return True
    return False

def parse_duration(duration_str: str) -> int:
    pattern = re.compile(r'(\d+)([dhms])')
    matches = pattern.findall(duration_str.lower())
    if not matches:
        return 0
    total_seconds = 0
    for value, unit in matches:
        value = int(value)
        if unit == 'd':
            total_seconds += value * 86400
        elif unit == 'h':
            total_seconds += value * 3600
        elif unit == 'm':
            total_seconds += value * 60
        elif unit == 's':
            total_seconds += value
    return total_seconds

async def send_punishment_notification(action: str, target: discord.Member, moderator: discord.Member, reason: str = None, duration: str = None):
    """Отправляет короткое уведомление в канал наказаний."""
    channel = bot.get_channel(PUNISHMENT_CHANNEL_ID)
    if not channel:
        return
    msg = f"**{action}** | {target.mention} | {moderator.mention}"
    if reason:
        msg += f" | Причина: {reason}"
    if duration:
        msg += f" | Длительность: {duration}"
    try:
        await channel.send(msg)
    except Exception as e:
        print(f"Ошибка отправки уведомления в канал наказаний: {e}")

async def log_action(interaction: discord.Interaction, action: str, target: discord.Member = None, reason: str = None, extra: str = None):
    """Отправляет подробный лог в основной лог-канал."""
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if not channel:
        return
    embed = discord.Embed(
        title=f"📋 {action}",
        color=discord.Color.blue(),
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="Модератор", value=interaction.user.mention, inline=False)
    if target:
        embed.add_field(name="Цель", value=f"{target.mention} ({target.id})", inline=False)
    if reason:
        embed.add_field(name="Причина", value=reason, inline=False)
    if extra:
        embed.add_field(name="Дополнительно", value=extra, inline=False)
    embed.set_footer(text=f"ID: {interaction.user.id}")
    try:
        await channel.send(embed=embed)
    except Exception as e:
        print(f"Ошибка отправки лога: {e}")

# ---------- Cog модерации ----------
class ModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="set_mod_role", description="Установить роль модератора (только владелец)")
    @app_commands.default_permissions(administrator=True)
    async def set_mod_role(self, interaction: discord.Interaction, role: discord.Role):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Только владелец бота может использовать эту команду.", ephemeral=True)
            return
        global MOD_ROLE_ID
        MOD_ROLE_ID = role.id
        await interaction.response.send_message(f"✅ Роль модератора установлена: {role.mention}", ephemeral=True)
        await log_action(interaction, "Назначена роль модератора", extra=f"Роль: {role.name} (ID: {role.id})")

    @app_commands.command(name="add_mod", description="Выдать роль модератора пользователю (только владелец)")
    @app_commands.default_permissions(administrator=True)
    async def add_mod(self, interaction: discord.Interaction, member: discord.Member):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Только владелец бота может использовать эту команду.", ephemeral=True)
            return
        if MOD_ROLE_ID == 0:
            await interaction.response.send_message("❌ Сначала установите роль модератора через /set_mod_role.", ephemeral=True)
            return
        role = interaction.guild.get_role(MOD_ROLE_ID)
        if not role:
            await interaction.response.send_message("❌ Роль модератора не найдена.", ephemeral=True)
            return
        try:
            await member.add_roles(role, reason=f"Выдана владельцем {interaction.user}")
            await interaction.response.send_message(f"✅ {member.mention} теперь модератор.", ephemeral=True)
            await log_action(interaction, "Выдана роль модератора", target=member)
        except Exception as e:
            await interaction.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)

    async def cog_check(self, interaction: discord.Interaction) -> bool:
        if not is_mod_or_owner(interaction):
            await interaction.response.send_message("⛔ У вас нет прав на использование этой команды.", ephemeral=True)
            return False
        return True

    @app_commands.command(name="ban", description="Забанить пользователя")
    @app_commands.describe(member="Пользователь", reason="Причина", delete_days="Удалить сообщения за N дней (0-7)")
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Не указана", delete_days: int = 0):
        if member.top_role >= interaction.user.top_role:
            await interaction.response.send_message("❌ Вы не можете забанить этого пользователя.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await member.ban(reason=f"{interaction.user}: {reason}", delete_message_days=delete_days)
            await interaction.followup.send(f"✅ Пользователь {member.mention} забанен.", ephemeral=True)
            await log_action(interaction, "Бан", target=member, reason=reason, extra=f"Удалено сообщений за {delete_days} дн.")
            await send_punishment_notification("Бан", member, interaction.user, reason)
        except Exception as e:
            await interaction.followup.send(f"❌ Ошибка: {e}", ephemeral=True)

    @app_commands.command(name="tempban", description="Временно забанить пользователя")
    @app_commands.describe(member="Пользователь", duration="Длительность (например: 1d, 2h, 30m)", reason="Причина")
    async def tempban(self, interaction: discord.Interaction, member: discord.Member, duration: str, reason: str = "Не указана"):
        if member.top_role >= interaction.user.top_role:
            await interaction.response.send_message("❌ Вы не можете забанить этого пользователя.", ephemeral=True)
            return
        seconds = parse_duration(duration)
        if seconds <= 0:
            await interaction.response.send_message("❌ Неверный формат длительности. Используйте: 1d, 2h, 30m и т.д.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await member.ban(reason=f"{interaction.user}: {reason} (временный на {duration})")
            await interaction.followup.send(f"✅ Пользователь {member.mention} забанен на {duration}.", ephemeral=True)
            await log_action(interaction, "Временный бан", target=member, reason=reason, extra=f"Длительность: {duration}")
            await send_punishment_notification("Временный бан", member, interaction.user, reason, duration)
            async def unban_after():
                await asyncio.sleep(seconds)
                try:
                    await member.unban(reason=f"Автоматический разбан после {duration}")
                except:
                    pass
            task = asyncio.create_task(unban_after())
            active_timers[member.id] = task
        except Exception as e:
            await interaction.followup.send(f"❌ Ошибка: {e}", ephemeral=True)

    @app_commands.command(name="kick", description="Кикнуть пользователя")
    @app_commands.describe(member="Пользователь", reason="Причина")
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Не указана"):
        if member.top_role >= interaction.user.top_role:
            await interaction.response.send_message("❌ Вы не можете кикнуть этого пользователя.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await member.kick(reason=f"{interaction.user}: {reason}")
            await interaction.followup.send(f"✅ Пользователь {member.mention} кикнут.", ephemeral=True)
            await log_action(interaction, "Кик", target=member, reason=reason)
            await send_punishment_notification("Кик", member, interaction.user, reason)
        except Exception as e:
            await interaction.followup.send(f"❌ Ошибка: {e}", ephemeral=True)

    @app_commands.command(name="mute", description="Замутить пользователя (таймаут)")
    @app_commands.describe(member="Пользователь", duration="Длительность (в минутах)", reason="Причина")
    async def mute(self, interaction: discord.Interaction, member: discord.Member, duration: int = 60, reason: str = "Не указана"):
        if member.top_role >= interaction.user.top_role:
            await interaction.response.send_message("❌ Вы не можете замутить этого пользователя.", ephemeral=True)
            return
        if duration > 40320:
            await interaction.response.send_message("❌ Максимальная длительность мута — 40320 минут (28 дней).", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await member.timeout(timedelta(minutes=duration), reason=f"{interaction.user}: {reason}")
            await interaction.followup.send(f"✅ Пользователь {member.mention} замучен на {duration} минут.", ephemeral=True)
            await log_action(interaction, "Мут", target=member, reason=reason, extra=f"Длительность: {duration} мин.")
            await send_punishment_notification("Мут", member, interaction.user, reason, f"{duration} мин.")
        except Exception as e:
            await interaction.followup.send(f"❌ Ошибка: {e}", ephemeral=True)

    @app_commands.command(name="tempmute", description="Замутить пользователя на время (таймаут)")
    @app_commands.describe(member="Пользователь", duration="Длительность (например: 1d, 2h, 30m)", reason="Причина")
    async def tempmute(self, interaction: discord.Interaction, member: discord.Member, duration: str, reason: str = "Не указана"):
        seconds = parse_duration(duration)
        if seconds <= 0:
            await interaction.response.send_message("❌ Неверный формат длительности. Используйте: 1d, 2h, 30m и т.д.", ephemeral=True)
            return
        if seconds > 40320*60:
            await interaction.response.send_message("❌ Максимальная длительность — 28 дней.", ephemeral=True)
            return
        if member.top_role >= interaction.user.top_role:
            await interaction.response.send_message("❌ Вы не можете замутить этого пользователя.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await member.timeout(timedelta(seconds=seconds), reason=f"{interaction.user}: {reason}")
            await interaction.followup.send(f"✅ Пользователь {member.mention} замучен на {duration}.", ephemeral=True)
            await log_action(interaction, "Временный мут", target=member, reason=reason, extra=f"Длительность: {duration}")
            await send_punishment_notification("Временный мут", member, interaction.user, reason, duration)
        except Exception as e:
            await interaction.followup.send(f"❌ Ошибка: {e}", ephemeral=True)

    @app_commands.command(name="unmute", description="Снять мут с пользователя")
    @app_commands.describe(member="Пользователь")
    async def unmute(self, interaction: discord.Interaction, member: discord.Member):
        if member.top_role >= interaction.user.top_role:
            await interaction.response.send_message("❌ Вы не можете снять мут с этого пользователя.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await member.timeout(None)
            await interaction.followup.send(f"✅ Мут снят с {member.mention}.", ephemeral=True)
            await log_action(interaction, "Снятие мута", target=member)
        except Exception as e:
            await interaction.followup.send(f"❌ Ошибка: {e}", ephemeral=True)

    @app_commands.command(name="clear", description="Удалить сообщения в канале (до 100)")
    @app_commands.describe(amount="Количество сообщений (1-100)")
    async def clear(self, interaction: discord.Interaction, amount: int = 10):
        if amount < 1 or amount > 100:
            await interaction.response.send_message("❌ Количество должно быть от 1 до 100.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            deleted = await interaction.channel.purge(limit=amount)
            await interaction.followup.send(f"✅ Удалено {len(deleted)} сообщений.", ephemeral=True)
            await log_action(interaction, "Очистка чата", extra=f"Удалено {len(deleted)} сообщений в {interaction.channel.mention}")
        except Exception as e:
            await interaction.followup.send(f"❌ Ошибка: {e}", ephemeral=True)

    @app_commands.command(name="warn", description="Выдать предупреждение пользователю")
    @app_commands.describe(member="Пользователь", reason="Причина")
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Не указана"):
        if member.top_role >= interaction.user.top_role:
            await interaction.response.send_message("❌ Вы не можете выдать предупреждение этому пользователю.", ephemeral=True)
            return
        warnings = load_warnings()
        user_id = str(member.id)
        if user_id not in warnings:
            warnings[user_id] = []
        warnings[user_id].append({
            "moderator": str(interaction.user.id),
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat()
        })
        save_warnings(warnings)
        await interaction.response.send_message(f"✅ {member.mention} получил предупреждение. Всего предупреждений: {len(warnings[user_id])}", ephemeral=True)
        await log_action(interaction, "Предупреждение", target=member, reason=reason)
        await send_punishment_notification("Предупреждение", member, interaction.user, reason)

    @app_commands.command(name="warnings", description="Показать предупреждения пользователя")
    @app_commands.describe(member="Пользователь")
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        warnings = load_warnings()
        user_id = str(member.id)
        if user_id not in warnings or not warnings[user_id]:
            await interaction.response.send_message(f"У {member.mention} нет предупреждений.", ephemeral=True)
            return
        embed = discord.Embed(title=f"Предупреждения для {member.display_name}", color=discord.Color.orange())
        for i, w in enumerate(warnings[user_id], 1):
            mod = interaction.guild.get_member(int(w['moderator']))
            mod_name = mod.display_name if mod else w['moderator']
            embed.add_field(
                name=f"#{i}",
                value=f"Модератор: {mod_name}\nПричина: {w['reason']}\nДата: {w['timestamp']}",
                inline=False
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="clearwarns", description="Очистить все предупреждения пользователя")
    @app_commands.describe(member="Пользователь")
    async def clearwarns(self, interaction: discord.Interaction, member: discord.Member):
        if member.top_role >= interaction.user.top_role:
            await interaction.response.send_message("❌ Вы не можете очистить предупреждения этого пользователя.", ephemeral=True)
            return
        warnings = load_warnings()
        user_id = str(member.id)
        if user_id in warnings:
            del warnings[user_id]
            save_warnings(warnings)
            await interaction.response.send_message(f"✅ Предупреждения для {member.mention} очищены.", ephemeral=True)
            await log_action(interaction, "Очистка предупреждений", target=member)
        else:
            await interaction.response.send_message(f"У {member.mention} нет предупреждений.", ephemeral=True)

    @app_commands.command(name="unban", description="Разбанить пользователя по ID")
    @app_commands.describe(user_id="ID пользователя", reason="Причина")
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = "Не указана"):
        await interaction.response.defer(ephemeral=True)
        try:
            user = discord.Object(id=int(user_id))
            await interaction.guild.unban(user, reason=f"{interaction.user}: {reason}")
            await interaction.followup.send(f"✅ Пользователь {user_id} разбанен.", ephemeral=True)
            await log_action(interaction, "Разбан", extra=f"ID: {user_id}, причина: {reason}")
        except Exception as e:
            await interaction.followup.send(f"❌ Ошибка: {e}", ephemeral=True)

# ---------- Веб-сервер ----------
async def health_check(request):
    return web.Response(text="OK", status=200)

async def start_web():
    app = web.Application()
    app.router.add_get('/health', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host='0.0.0.0', port=8080)
    await site.start()
    print("🌐 Health check на порту 8080")
    await asyncio.Event().wait()

@bot.event
async def on_ready():
    print(f'✅ Бот {bot.user} запущен!')
    try:
        synced = await bot.tree.sync()
        print(f"🔄 Синхронизировано {len(synced)} команд.")
    except Exception as e:
        print(f"⚠️ Ошибка синхронизации: {e}")

async def main():
    await bot.add_cog(ModerationCog(bot))
    asyncio.create_task(start_web())
    await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
