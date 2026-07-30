import discord
from discord import app_commands
from discord.ext import commands

# ---- Настройки (можно переопределить в основном коде) ----
# Ожидаем, что эти переменные определены в основном файле
# или передаются через параметры.

async def check_permissions(
    interaction: discord.Interaction,
    owner_id: int,
    allowed_role_ids: list = None,
    guild_id: int = None
) -> bool:
    """
    Универсальная проверка прав для команд.
    Возвращает True, если пользователь может использовать команду.
    Отправляет сообщение об ошибке, если нет.
    """
    # 1. Проверка на владельца
    if interaction.user.id == owner_id:
        return True

    # 2. Проверка на сервер (если задан guild_id)
    if guild_id is not None and interaction.guild_id != guild_id:
        await interaction.response.send_message(
            "⛔ Это приложение не предназначено для использования на этом сервере.",
            ephemeral=True
        )
        return False

    # 3. Проверка ролей (если переданы)
    if allowed_role_ids:
        for role_id in allowed_role_ids:
            role = interaction.guild.get_role(role_id)
            if role and role in interaction.user.roles:
                return True

    # 4. Если ничего не подошло – запрет
    await interaction.response.send_message(
        "⛔ Вам нельзя использовать команды на этом сервере.",
        ephemeral=True
    )
    return False

# ---- Декоратор для команд (можно использовать как альтернативу) ----
def require_permissions(owner_id, allowed_roles=None, guild_id=None):
    """
    Декоратор для проверки прав перед выполнением команды.
    Использование:
        @require_permissions(OWNER_ID, ALLOWED_ROLES, GUILD_ID)
        async def my_command(self, interaction: discord.Interaction):
            ...
    """
    def decorator(func):
        async def wrapper(self, interaction: discord.Interaction, *args, **kwargs):
            if not await check_permissions(interaction, owner_id, allowed_roles, guild_id):
                return
            return await func(self, interaction, *args, **kwargs)
        return wrapper
    return decorator
