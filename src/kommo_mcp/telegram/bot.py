"""
Telegram Bot for KommoMCP SaaS.
Handles user registration, API key setup, and AI chat.
"""

import os
import asyncio
import logging
from typing import Optional

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from kommo_mcp.saas.manager import TenantManager
from kommo_mcp.saas.orchestrator import Orchestrator
from kommo_mcp.saas.tenant import TenantStatus

logger = logging.getLogger(__name__)

# FSM States
class SetupStates(StatesGroup):
    waiting_kommo_domain = State()
    waiting_kommo_token = State()
    waiting_openai_key = State()


class KommoBot:
    """Main bot class."""
    
    def __init__(
        self,
        token: str,
        tenant_manager: TenantManager,
        orchestrator: Orchestrator,
    ):
        self.bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        self.dp = Dispatcher(storage=MemoryStorage())
        self.router = Router()
        self.tenant_manager = tenant_manager
        self.orchestrator = orchestrator
        
        self._setup_handlers()
    
    def _setup_handlers(self):
        """Register all command handlers."""
        
        @self.router.message(CommandStart())
        async def cmd_start(message: Message):
            """Handle /start command - register new user."""
            user_id = message.from_user.id
            username = message.from_user.username
            
            tenant = await self.tenant_manager.register(user_id, username)
            
            welcome = (
                f'👋 <b>Добро пожаловать в KommoMCP!</b>\n\n'
                f'Я помогу вам работать с вашей CRM через AI.\n\n'
                f'<b>Статус:</b> {self._format_status(tenant.status)}\n\n'
                f'<b>Для начала работы:</b>\n'
                f'1️⃣ /connect - подключить Kommo CRM\n'
                f'2️⃣ /openai - добавить OpenAI ключ\n'
                f'3️⃣ /ask - задать вопрос по CRM\n\n'
                f'/help - все команды'
            )
            await message.answer(welcome)
        
        @self.router.message(Command('help'))
        async def cmd_help(message: Message):
            """Show help message."""
            help_text = (
                '<b>📚 Команды:</b>\n\n'
                '/start - начать работу\n'
                '/connect - подключить Kommo CRM\n'
                '/openai - добавить OpenAI API ключ\n'
                '/status - статус подключения\n'
                '/ask <вопрос> - задать вопрос по CRM\n'
                '/sync - синхронизировать данные\n'
                '/disconnect - отключить CRM\n\n'
                '<b>Примеры вопросов:</b>\n'
                '• Покажи аналитику воронки\n'
                '• Сколько сделок в работе?\n'
                '• Кто лучший менеджер?\n'
                '• Какие сделки просрочены?'
            )
            await message.answer(help_text)
        
        @self.router.message(Command('status'))
        async def cmd_status(message: Message):
            """Show connection status."""
            tenant = await self.tenant_manager.get_by_telegram_id(message.from_user.id)
            
            if not tenant:
                await message.answer('❌ Вы не зарегистрированы. Используйте /start')
                return
            
            container_status = None
            if tenant.container_id:
                container_status = await self.orchestrator.get_container_status(tenant.id)
            
            status_text = (
                f'<b>📊 Статус подключения</b>\n\n'
                f'<b>Kommo:</b> {"✅ Подключено" if tenant.has_kommo_credentials() else "❌ Не подключено"}\n'
                f'<b>OpenAI:</b> {"✅ Настроено" if tenant.has_openai_credentials() else "❌ Не настроено"}\n'
                f'<b>Статус:</b> {self._format_status(tenant.status)}\n'
            )
            
            if tenant.kommo_domain:
                status_text += f'<b>Домен:</b> {tenant.kommo_domain}\n'
            
            if container_status:
                status_text += f'<b>Контейнер:</b> {container_status}\n'
            
            if tenant.last_sync_at:
                status_text += f'<b>Последняя синхронизация:</b> {tenant.last_sync_at.strftime("%d.%m.%Y %H:%M")}\n'
            
            status_text += f'\n<b>Запросов сегодня:</b> {tenant.requests_today}/{tenant.requests_limit}'
            
            await message.answer(status_text)
        
        @self.router.message(Command('connect'))
        async def cmd_connect(message: Message, state: FSMContext):
            """Start Kommo connection flow."""
            await message.answer(
                '<b>🔗 Подключение Kommo CRM</b>\n\n'
                'Введите домен вашего аккаунта Kommo:\n'
                '(например: <code>mycompany</code> или <code>mycompany.kommo.com</code>)'
            )
            await state.set_state(SetupStates.waiting_kommo_domain)
        
        @self.router.message(SetupStates.waiting_kommo_domain)
        async def process_kommo_domain(message: Message, state: FSMContext):
            """Process Kommo domain input."""
            domain = message.text.strip().lower()
            
            # Normalize domain - support both kommo.com and amocrm.ru
            if not (domain.endswith('.kommo.com') or domain.endswith('.amocrm.ru')):
                # Default to amocrm.ru for Russian users
                domain = f'{domain}.amocrm.ru'
            
            await state.update_data(kommo_domain=domain)
            
            await message.answer(
                f'<b>Домен:</b> {domain}\n\n'
                'Теперь введите <b>Access Token</b> от Kommo API.\n\n'
                '📖 <a href="https://www.kommo.com/ru/support/digital-pipeline/api-and-integrations/">Как получить токен</a>'
            )
            await state.set_state(SetupStates.waiting_kommo_token)
        
        @self.router.message(SetupStates.waiting_kommo_token)
        async def process_kommo_token(message: Message, state: FSMContext):
            """Process Kommo access token."""
            token = message.text.strip()
            data = await state.get_data()
            domain = data.get('kommo_domain')
            
            # Delete message with token for security
            try:
                await message.delete()
            except Exception:
                pass
            
            tenant = await self.tenant_manager.get_by_telegram_id(message.from_user.id)
            if not tenant:
                await message.answer('❌ Ошибка. Используйте /start')
                await state.clear()
                return
            
            # Validate token by making test request
            is_valid = await self._validate_kommo_token(domain, token)
            
            if not is_valid:
                await message.answer(
                    '❌ <b>Ошибка валидации токена</b>\n\n'
                    'Проверьте правильность домена и токена.\n'
                    'Используйте /connect чтобы попробовать снова.'
                )
                await state.clear()
                return
            
            # Save credentials
            await self.tenant_manager.set_kommo_credentials(
                tenant.id, domain, token
            )
            
            await state.clear()
            
            # Check if OpenAI is configured
            tenant = await self.tenant_manager.get_by_id(tenant.id)
            
            if tenant.has_openai_credentials():
                # Start provisioning
                await message.answer(
                    '✅ <b>Kommo подключен!</b>\n\n'
                    '⏳ Создаю инфраструктуру...'
                )
                success, msg = await self.orchestrator.provision(tenant.id)
                
                if success:
                    await message.answer(
                        f'✅ <b>Готово!</b>\n\n'
                        f'{msg}\n\n'
                        f'Теперь вы можете использовать /ask для запросов к CRM.'
                    )
                else:
                    await message.answer(f'❌ <b>Ошибка:</b> {msg}')
            else:
                await message.answer(
                    '✅ <b>Kommo подключен!</b>\n\n'
                    'Теперь добавьте OpenAI API ключ:\n'
                    '/openai'
                )
        
        @self.router.message(Command('openai'))
        async def cmd_openai(message: Message, state: FSMContext):
            """Start OpenAI key setup."""
            await message.answer(
                '<b>🤖 Настройка OpenAI</b>\n\n'
                'Введите ваш OpenAI API ключ:\n'
                '(начинается с <code>sk-</code>)\n\n'
                '📖 <a href="https://platform.openai.com/api-keys">Получить ключ</a>'
            )
            await state.set_state(SetupStates.waiting_openai_key)
        
        @self.router.message(SetupStates.waiting_openai_key)
        async def process_openai_key(message: Message, state: FSMContext):
            """Process OpenAI API key."""
            api_key = message.text.strip()
            
            # Delete message with key for security
            try:
                await message.delete()
            except Exception:
                pass
            
            if not api_key.startswith('sk-'):
                await message.answer(
                    '❌ Неверный формат ключа.\n'
                    'OpenAI ключ должен начинаться с <code>sk-</code>'
                )
                return
            
            tenant = await self.tenant_manager.get_by_telegram_id(message.from_user.id)
            if not tenant:
                await message.answer('❌ Ошибка. Используйте /start')
                await state.clear()
                return
            
            # Validate key
            is_valid = await self._validate_openai_key(api_key)
            
            if not is_valid:
                await message.answer(
                    '❌ <b>Ошибка валидации ключа</b>\n\n'
                    'Проверьте правильность ключа.\n'
                    'Используйте /openai чтобы попробовать снова.'
                )
                await state.clear()
                return
            
            # Save key
            await self.tenant_manager.set_openai_key(tenant.id, api_key)
            await state.clear()
            
            # Check if Kommo is configured
            tenant = await self.tenant_manager.get_by_id(tenant.id)
            
            if tenant.has_kommo_credentials():
                # Start provisioning if not already done
                if tenant.status in (TenantStatus.PENDING, TenantStatus.ERROR):
                    await message.answer(
                        '✅ <b>OpenAI настроен!</b>\n\n'
                        '⏳ Создаю инфраструктуру...'
                    )
                    success, msg = await self.orchestrator.provision(tenant.id)
                    
                    if success:
                        await message.answer(
                            f'✅ <b>Готово!</b>\n\n'
                            f'{msg}\n\n'
                            f'Теперь вы можете использовать /ask для запросов к CRM.'
                        )
                    else:
                        await message.answer(f'❌ <b>Ошибка:</b> {msg}')
                else:
                    await message.answer(
                        '✅ <b>OpenAI настроен!</b>\n\n'
                        'Используйте /ask для запросов к CRM.'
                    )
            else:
                await message.answer(
                    '✅ <b>OpenAI настроен!</b>\n\n'
                    'Теперь подключите Kommo CRM:\n'
                    '/connect'
                )
        
        @self.router.message(Command('sync'))
        async def cmd_sync(message: Message):
            """Trigger data sync."""
            tenant = await self.tenant_manager.get_by_telegram_id(message.from_user.id)
            
            if not tenant or not tenant.is_ready():
                await message.answer('❌ Сначала настройте подключение: /connect и /openai')
                return
            
            await message.answer('⏳ Синхронизирую данные...')
            
            success, msg = await self.orchestrator.trigger_sync(tenant.id)
            
            if success:
                await message.answer('✅ Синхронизация завершена!')
            else:
                await message.answer(f'❌ Ошибка синхронизации: {msg}')
        
        @self.router.message(Command('disconnect'))
        async def cmd_disconnect(message: Message):
            """Disconnect and deprovision."""
            tenant = await self.tenant_manager.get_by_telegram_id(message.from_user.id)
            
            if not tenant:
                await message.answer('❌ Вы не зарегистрированы.')
                return
            
            await message.answer('⏳ Отключаю...')
            
            success, msg = await self.orchestrator.deprovision(tenant.id)
            
            if success:
                await message.answer(
                    '✅ <b>Отключено</b>\n\n'
                    'Ваши данные сохранены. Используйте /connect для повторного подключения.'
                )
            else:
                await message.answer(f'❌ Ошибка: {msg}')
        
        @self.router.message(Command('ask'))
        async def cmd_ask(message: Message):
            """Handle AI question."""
            tenant = await self.tenant_manager.get_by_telegram_id(message.from_user.id)
            
            if not tenant or not tenant.is_ready():
                await message.answer('❌ Сначала настройте подключение: /connect и /openai')
                return
            
            # Extract question from command
            question = message.text.replace('/ask', '').strip()
            
            if not question:
                await message.answer(
                    'Введите вопрос после команды:\n'
                    '<code>/ask Покажи аналитику воронки</code>'
                )
                return
            
            # Check rate limit
            if not await self.tenant_manager.increment_requests(tenant.id):
                await message.answer(
                    '⚠️ <b>Лимит запросов исчерпан</b>\n\n'
                    f'Ваш лимит: {tenant.requests_limit} запросов в день.\n'
                    'Лимит сбрасывается в полночь.'
                )
                return
            
            await message.answer('🤔 Думаю...')
            
            # Process with AI
            response = await self._process_ai_request(tenant, question)
            
            await message.answer(response)
        
        @self.router.message(F.text & ~F.text.startswith('/'))
        async def handle_text(message: Message, state: FSMContext):
            """Handle plain text as AI question."""
            current_state = await state.get_state()
            if current_state:
                # In FSM flow, ignore
                return
            
            tenant = await self.tenant_manager.get_by_telegram_id(message.from_user.id)
            
            if not tenant:
                await message.answer('👋 Используйте /start для начала работы')
                return
            
            if not tenant.is_ready():
                await message.answer('❌ Сначала настройте подключение: /connect и /openai')
                return
            
            # Check rate limit
            if not await self.tenant_manager.increment_requests(tenant.id):
                await message.answer('⚠️ Лимит запросов исчерпан на сегодня.')
                return
            
            await message.answer('🤔 Думаю...')
            
            response = await self._process_ai_request(tenant, message.text)
            await message.answer(response)
        
        # Register router
        self.dp.include_router(self.router)
    
    def _format_status(self, status: TenantStatus) -> str:
        """Format status for display."""
        status_map = {
            TenantStatus.PENDING: '⏳ Ожидает настройки',
            TenantStatus.PROVISIONING: '🔄 Создание инфраструктуры',
            TenantStatus.SYNCING: '📥 Синхронизация данных',
            TenantStatus.ACTIVE: '✅ Активен',
            TenantStatus.SUSPENDED: '⏸️ Приостановлен',
            TenantStatus.ERROR: '❌ Ошибка',
        }
        return status_map.get(status, str(status))
    
    async def _validate_kommo_token(self, domain: str, token: str) -> bool:
        """Validate Kommo API token."""
        try:
            import aiohttp
            
            url = f'https://{domain}/api/v4/account'
            headers = {'Authorization': f'Bearer {token}'}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    return resp.status == 200
        except Exception as e:
            logger.error(f'Kommo validation error: {e}')
            return False
    
    async def _validate_openai_key(self, api_key: str) -> bool:
        """Validate OpenAI API key."""
        try:
            import aiohttp
            
            url = 'https://api.openai.com/v1/models'
            headers = {'Authorization': f'Bearer {api_key}'}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    return resp.status == 200
        except Exception as e:
            logger.error(f'OpenAI validation error: {e}')
            return False
    
    async def _process_ai_request(self, tenant, question: str) -> str:
        """Process AI request using OpenAI and direct Kommo API."""
        try:
            from kommo_mcp.telegram.ai_chat import AIChat
            
            ai = AIChat(
                openai_api_key=tenant.openai_api_key,
                kommo_domain=tenant.kommo_domain,
                kommo_token=tenant.kommo_access_token,
            )
            
            response = await ai.chat(question)
            return response
        except Exception as e:
            logger.error(f'AI request error: {e}')
            return f'❌ Ошибка обработки запроса: {e}'
    
    async def start(self):
        """Start the bot."""
        await self.tenant_manager.init()
        await self.orchestrator.init()
        await self.dp.start_polling(self.bot)


def create_bot(
    token: str,
    tenant_manager: TenantManager,
    orchestrator: Orchestrator,
) -> KommoBot:
    """Create bot instance."""
    return KommoBot(token, tenant_manager, orchestrator)


async def run_bot(token: str, data_dir: str = '/var/lib/kommo-saas'):
    """Run the bot with default configuration."""
    tenant_manager = TenantManager(data_dir=data_dir)
    orchestrator = Orchestrator(
        tenant_manager=tenant_manager,
        postgres_host=os.getenv('POSTGRES_HOST', 'localhost'),
        postgres_port=int(os.getenv('POSTGRES_PORT', '5432')),
        postgres_user=os.getenv('POSTGRES_USER', 'postgres'),
        postgres_password=os.getenv('POSTGRES_PASSWORD', ''),
    )
    
    bot = create_bot(token, tenant_manager, orchestrator)
    await bot.start()
