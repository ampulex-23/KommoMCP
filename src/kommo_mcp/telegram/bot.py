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
from aiogram.types import Message, CallbackQuery, BotCommand
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from kommo_mcp.saas.manager import TenantManager
from kommo_mcp.saas.orchestrator import Orchestrator
from kommo_mcp.saas.tenant import TenantStatus
from kommo_mcp.telegram.setup_wizard import get_wizard

logger = logging.getLogger(__name__)

# Admin user IDs who can view logs
ADMIN_USER_IDS = {123456789}  # TODO: Configure via env

# FSM States
class SetupStates(StatesGroup):
    waiting_crm_label = State()
    waiting_kommo_domain = State()
    waiting_kommo_token = State()
    waiting_openai_key = State()
    waiting_switch_choice = State()
    waiting_remove_choice = State()


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
            """Handle /start command - greet user."""
            user_id = message.from_user.id
            tenants = await self.tenant_manager.get_tenants_for_user(user_id)
            
            if tenants:
                active = await self.tenant_manager.get_active_tenant(user_id)
                active_label = active.label or active.kommo_domain or 'без имени' if active else '—'
                welcome = (
                    f'\U0001f44b <b>С возвращением в KommoMCP!</b>\n\n'
                    f'У вас подключено CRM: <b>{len(tenants)}</b>\n'
                    f'Активная: <b>{active_label}</b>\n\n'
                    f'/crm_list - список CRM\n'
                    f'/connect - подключить ещё одну CRM\n'
                    f'/switch - переключить активную CRM\n'
                    f'/ask - задать вопрос по CRM\n\n'
                    f'/help - все команды'
                )
            else:
                welcome = (
                    f'\U0001f44b <b>Добро пожаловать в KommoMCP!</b>\n\n'
                    f'Я помогу вам работать с вашей CRM через AI.\n\n'
                    f'<b>Для начала работы:</b>\n'
                    f'1\ufe0f\u20e3 /connect - подключить Kommo CRM\n'
                    f'2\ufe0f\u20e3 /openai - добавить OpenAI ключ\n'
                    f'3\ufe0f\u20e3 /ask - задать вопрос по CRM\n\n'
                    f'/help - все команды'
                )
            await message.answer(welcome)
        
        @self.router.message(Command('help'))
        async def cmd_help(message: Message):
            """Show help message."""
            help_text = (
                '<b>\U0001f4da Команды:</b>\n\n'
                '<b>CRM-подключения:</b>\n'
                '/connect - подключить новую CRM\n'
                '/crm_list - список всех CRM\n'
                '/switch - переключить активную CRM\n'
                '/remove_crm - отключить CRM\n'
                '/openai - добавить OpenAI API ключ\n'
                '/status - статус текущей CRM\n\n'
                '<b>Работа:</b>\n'
                '/wizard - \U0001f9d9\u200d\u2642\ufe0f мастер настройки CRM\n'
                '/ask <вопрос> - задать вопрос по CRM\n'
                '/cancel - отменить текущую операцию\n\n'
                '<b>Примеры вопросов:</b>\n'
                '\u2022 Покажи аналитику воронки\n'
                '\u2022 Сколько сделок в работе?\n'
                '\u2022 Создай воронку для продаж\n'
                '\u2022 Какие сделки просрочены?'
            )
            await message.answer(help_text)
        
        @self.router.message(Command('wizard'))
        async def cmd_wizard(message: Message):
            """Start CRM setup wizard."""
            tenant = await self.tenant_manager.get_active_tenant(message.from_user.id)
            
            if not tenant:
                await message.answer('❌ Сначала зарегистрируйтесь: /start')
                return
            
            if not tenant.has_kommo_credentials():
                await message.answer('❌ Сначала подключите Kommo CRM: /connect')
                return
            
            if not tenant.has_openai_credentials():
                await message.answer('❌ Сначала добавьте OpenAI ключ: /openai')
                return
            
            wizard = get_wizard()
            response = wizard.start(message.from_user.id)
            await message.answer(response)
        
        @self.router.message(Command('cancel'))
        async def cmd_cancel(message: Message, state: FSMContext):
            """Cancel current operation."""
            # Cancel wizard if active
            wizard = get_wizard()
            if wizard.is_active(message.from_user.id):
                response = wizard.cancel(message.from_user.id)
                await message.answer(response)
                return
            
            # Cancel FSM state
            await state.clear()
            await message.answer('Операция отменена.')
        
        @self.router.message(Command('status'))
        async def cmd_status(message: Message):
            """Show connection status for active CRM."""
            user_id = message.from_user.id
            tenant = await self.tenant_manager.get_active_tenant(user_id)
            all_tenants = await self.tenant_manager.get_tenants_for_user(user_id)
            
            if not tenant:
                await message.answer('❌ Нет подключённых CRM. Используйте /connect')
                return
            
            container_status = None
            if tenant.container_id:
                container_status = await self.orchestrator.get_container_status(tenant.id)
            
            label = tenant.label or tenant.kommo_domain or 'без имени'
            status_text = (
                f'<b>\U0001f4ca Статус: {label}</b>'
            )
            if len(all_tenants) > 1:
                status_text += f' (1 из {len(all_tenants)} CRM)'
            status_text += '\n\n'
            
            kommo_status = '\u2705 Подключено' if tenant.has_kommo_credentials() else '\u274c Не подключено'
            openai_status = '\u2705 Настроено' if tenant.has_openai_credentials() else '\u274c Не настроено'
            status_text += (
                f'<b>Kommo:</b> {kommo_status}\n'
                f'<b>OpenAI:</b> {openai_status}\n'
                f'<b>Статус:</b> {self._format_status(tenant.status)}\n'
            )
            
            if tenant.kommo_domain:
                status_text += f'<b>Домен:</b> {tenant.kommo_domain}\n'
            
            if container_status:
                status_text += f'<b>Контейнер:</b> {container_status}\n'
            
            if tenant.last_sync_at:
                status_text += f'<b>Последняя синхронизация:</b> {tenant.last_sync_at.strftime("%d.%m.%Y %H:%M")}\n'
            
            status_text += f'\n<b>Запросов сегодня:</b> {tenant.requests_today}/{tenant.requests_limit}'
            
            if len(all_tenants) > 1:
                status_text += '\n\n/crm_list - все CRM | /switch - переключить'
            
            await message.answer(status_text)
        
        @self.router.message(Command('crm_list'))
        async def cmd_crm_list(message: Message):
            """Show all connected CRMs."""
            user_id = message.from_user.id
            tenants = await self.tenant_manager.get_tenants_for_user(user_id)
            active = await self.tenant_manager.get_active_tenant(user_id)
            
            if not tenants:
                await message.answer('❌ Нет подключённых CRM. Используйте /connect')
                return
            
            lines = ['<b>\U0001f4cb Ваши CRM-подключения:</b>\n']
            for i, t in enumerate(tenants, 1):
                label = t.label or t.kommo_domain or 'без имени'
                status_icon = '\u2705' if t.is_ready() else '\u23f3'
                active_mark = ' \u25c0 активная' if active and t.id == active.id else ''
                domain = t.kommo_domain or '—'
                lines.append(f'{i}. {status_icon} <b>{label}</b> ({domain}){active_mark}')
            
            lines.append('')
            lines.append('/connect - добавить CRM')
            if len(tenants) > 1:
                lines.append('/switch - переключить активную')
            lines.append('/remove_crm - отключить CRM')
            
            await message.answer('\n'.join(lines))
        
        @self.router.message(Command('switch'))
        async def cmd_switch(message: Message, state: FSMContext):
            """Switch active CRM."""
            user_id = message.from_user.id
            tenants = await self.tenant_manager.get_tenants_for_user(user_id)
            
            if len(tenants) <= 1:
                await message.answer('У вас только одна CRM. Добавьте ещё: /connect')
                return
            
            active = await self.tenant_manager.get_active_tenant(user_id)
            lines = ['<b>\U0001f504 Выберите CRM (введите номер):</b>\n']
            for i, t in enumerate(tenants, 1):
                label = t.label or t.kommo_domain or 'без имени'
                active_mark = ' \u25c0' if active and t.id == active.id else ''
                lines.append(f'{i}. <b>{label}</b> ({t.kommo_domain or "—"}){active_mark}')
            
            await state.update_data(switch_tenants=[t.id for t in tenants])
            await message.answer('\n'.join(lines))
            await state.set_state(SetupStates.waiting_switch_choice)
        
        @self.router.message(SetupStates.waiting_switch_choice)
        async def process_switch_choice(message: Message, state: FSMContext):
            """Process CRM switch selection."""
            data = await state.get_data()
            tenant_ids = data.get('switch_tenants', [])
            
            try:
                idx = int(message.text.strip()) - 1
                if 0 <= idx < len(tenant_ids):
                    tid = tenant_ids[idx]
                    await self.tenant_manager.set_active_tenant(message.from_user.id, tid)
                    tenant = await self.tenant_manager.get_by_id(tid)
                    label = tenant.label or tenant.kommo_domain or 'без имени'
                    await state.clear()
                    await message.answer(f'\u2705 Активная CRM: <b>{label}</b>')
                else:
                    await message.answer('❌ Неверный номер. Попробуйте ещё раз или /cancel')
            except ValueError:
                await message.answer('❌ Введите номер CRM или /cancel')
        
        @self.router.message(Command('remove_crm'))
        async def cmd_remove_crm(message: Message, state: FSMContext):
            """Remove a CRM connection."""
            user_id = message.from_user.id
            tenants = await self.tenant_manager.get_tenants_for_user(user_id)
            
            if not tenants:
                await message.answer('❌ Нет подключённых CRM.')
                return
            
            lines = ['<b>\U0001f5d1 Выберите CRM для отключения (введите номер):</b>\n']
            for i, t in enumerate(tenants, 1):
                label = t.label or t.kommo_domain or 'без имени'
                lines.append(f'{i}. <b>{label}</b> ({t.kommo_domain or "—"})')
            
            await state.update_data(remove_tenants=[t.id for t in tenants])
            await message.answer('\n'.join(lines))
            await state.set_state(SetupStates.waiting_remove_choice)
        
        @self.router.message(SetupStates.waiting_remove_choice)
        async def process_remove_choice(message: Message, state: FSMContext):
            """Process CRM removal selection."""
            data = await state.get_data()
            tenant_ids = data.get('remove_tenants', [])
            
            try:
                idx = int(message.text.strip()) - 1
                if 0 <= idx < len(tenant_ids):
                    tid = tenant_ids[idx]
                    tenant = await self.tenant_manager.get_by_id(tid)
                    label = tenant.label or tenant.kommo_domain or 'без имени' if tenant else '?'
                    
                    # Deprovision infrastructure
                    if tenant and tenant.container_id:
                        await self.orchestrator.deprovision(tid)
                    
                    await self.tenant_manager.remove_tenant(message.from_user.id, tid)
                    await state.clear()
                    await message.answer(f'\u2705 CRM <b>{label}</b> отключена.')
                else:
                    await message.answer('❌ Неверный номер. Попробуйте ещё раз или /cancel')
            except ValueError:
                await message.answer('❌ Введите номер CRM или /cancel')
        
        @self.router.message(Command('connect'))
        async def cmd_connect(message: Message, state: FSMContext):
            """Start Kommo connection flow — adds a new CRM."""
            await message.answer(
                '<b>\U0001f517 Подключение новой CRM</b>\n\n'
                'Введите название для этой CRM (например: <code>Автосалон</code> или <code>Фитнес-клуб</code>):'
            )
            await state.set_state(SetupStates.waiting_crm_label)
        
        @self.router.message(SetupStates.waiting_crm_label)
        async def process_crm_label(message: Message, state: FSMContext):
            """Process CRM label input."""
            label = message.text.strip()[:50]  # Limit label length
            await state.update_data(crm_label=label)
            await message.answer(
                f'<b>CRM:</b> {label}\n\n'
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
            label = data.get('crm_label')
            
            # Delete message with token for security
            try:
                await message.delete()
            except Exception:
                pass
            
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
            
            # Register new tenant for this CRM
            tenant = await self.tenant_manager.register(
                telegram_user_id=message.from_user.id,
                telegram_username=message.from_user.username,
                label=label,
            )
            
            # Save credentials
            await self.tenant_manager.set_kommo_credentials(
                tenant.id, domain, token
            )
            
            # Auto-switch to the new CRM
            await self.tenant_manager.set_active_tenant(message.from_user.id, tenant.id)
            
            await state.clear()
            
            # Check if OpenAI is configured (try to copy from another tenant)
            tenant = await self.tenant_manager.get_by_id(tenant.id)
            other_tenants = await self.tenant_manager.get_tenants_for_user(message.from_user.id)
            for ot in other_tenants:
                if ot.id != tenant.id and ot.has_openai_credentials():
                    await self.tenant_manager.set_openai_key(tenant.id, ot.openai_api_key)
                    tenant = await self.tenant_manager.get_by_id(tenant.id)
                    break
            
            display_label = label or domain
            
            if tenant.has_openai_credentials():
                # Start provisioning
                await message.answer(
                    f'✅ <b>CRM "{display_label}" подключена!</b>\n\n'
                    '⏳ Создаю инфраструктуру...'
                )
                success, msg = await self.orchestrator.provision(tenant.id)
                
                if success:
                    await message.answer(
                        f'✅ <b>Готово!</b>\n\n'
                        f'{msg}\n\n'
                        f'CRM <b>{display_label}</b> теперь активная.\n'
                        f'Используйте /ask для запросов.'
                    )
                else:
                    await message.answer(f'❌ <b>Ошибка:</b> {msg}')
            else:
                await message.answer(
                    f'✅ <b>CRM "{display_label}" подключена!</b>\n\n'
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
            """Process OpenAI API key — applies to ALL user's CRMs."""
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
            
            # Save key to ALL user's tenants
            tenants = await self.tenant_manager.get_tenants_for_user(message.from_user.id)
            for t in tenants:
                await self.tenant_manager.set_openai_key(t.id, api_key)
            
            await state.clear()
            
            # Provision any tenants that were waiting for OpenAI key
            provisioned = []
            for t in tenants:
                t = await self.tenant_manager.get_by_id(t.id)
                if t.has_kommo_credentials() and t.status in (TenantStatus.PENDING, TenantStatus.ERROR):
                    success, msg = await self.orchestrator.provision(t.id)
                    if success:
                        provisioned.append(t.label or t.kommo_domain)
            
            if provisioned:
                names = ', '.join(provisioned)
                await message.answer(
                    f'✅ <b>OpenAI настроен для всех CRM!</b>\n\n'
                    f'Активированы: {names}\n\n'
                    f'Используйте /ask для запросов.'
                )
            elif tenants:
                await message.answer(
                    '✅ <b>OpenAI настроен для всех CRM!</b>\n\n'
                    'Используйте /ask для запросов.'
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
            tenant = await self.tenant_manager.get_active_tenant(message.from_user.id)
            
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
            """Disconnect active CRM (legacy, redirects to /remove_crm)."""
            await message.answer(
                'Используйте /remove_crm для отключения CRM.\n'
                '/crm_list - посмотреть все подключения'
            )
        
        @self.router.message(Command('ask'))
        async def cmd_ask(message: Message):
            """Handle AI question."""
            tenant = await self.tenant_manager.get_active_tenant(message.from_user.id)
            
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
            
            # Process with AI (pass user_id for conversation history)
            response = await self._process_ai_request(tenant, question, user_id=message.from_user.id)
            
            # Send with HTML parse mode for rich formatting
            try:
                await message.answer(response, parse_mode='HTML')
            except Exception:
                # Fallback to plain text if HTML parsing fails
                await message.answer(response)
        
        @self.router.message(F.text & ~F.text.startswith('/'))
        async def handle_text(message: Message, state: FSMContext):
            """Handle plain text as AI question or wizard answer."""
            current_state = await state.get_state()
            if current_state:
                # In FSM flow, ignore
                return
            
            tenant = await self.tenant_manager.get_active_tenant(message.from_user.id)
            
            if not tenant:
                await message.answer('👋 Используйте /start для начала работы')
                return
            
            # Check if wizard is active
            wizard = get_wizard()
            if wizard.is_active(message.from_user.id):
                response = await wizard.process_answer(message.from_user.id, message.text)
                await message.answer(response)
                
                # Check if wizard completed and needs to execute setup
                wizard_state = wizard.get_state(message.from_user.id)
                if wizard_state and wizard_state.confirmed:
                    # Get setup prompt and execute
                    setup_prompt = wizard.get_setup_prompt(message.from_user.id)
                    if setup_prompt and tenant.is_ready():
                        await message.answer('🤔 Выполняю настройку...')
                        ai_response = await self._process_ai_request(tenant, setup_prompt, user_id=message.from_user.id)
                        try:
                            await message.answer(ai_response, parse_mode='HTML')
                        except Exception:
                            await message.answer(ai_response)
                return
            
            if not tenant.is_ready():
                await message.answer('❌ Сначала настройте подключение: /connect и /openai')
                return
            
            # Check rate limit
            if not await self.tenant_manager.increment_requests(tenant.id):
                await message.answer('⚠️ Лимит запросов исчерпан на сегодня.')
                return
            
            await message.answer('🤔 Думаю...')
            
            # Process with AI (pass user_id:tenant_id for conversation history isolation)
            response = await self._process_ai_request(tenant, message.text, user_id=message.from_user.id)
            
            # Send with HTML parse mode for rich formatting
            try:
                await message.answer(response, parse_mode='HTML')
            except Exception:
                # Fallback to plain text if HTML parsing fails
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
    
    async def _process_ai_request(self, tenant, question: str, user_id: int = None) -> str:
        """Process AI request using OpenAI and direct Kommo API."""
        try:
            from kommo_mcp.telegram.ai_chat import AIChat
            
            ai = AIChat(
                openai_api_key=tenant.openai_api_key,
                kommo_domain=tenant.kommo_domain,
                kommo_token=tenant.kommo_access_token,
            )
            
            # Pass user_id for conversation history
            history_key = f'{user_id or tenant.telegram_user_id}:{tenant.id}'
            response = await ai.chat(question, user_id=history_key)
            return response
        except Exception as e:
            logger.error(f'AI request error: {e}')
            return f'❌ Ошибка обработки запроса: {e}'
    
    async def _set_bot_commands(self):
        """Set bot menu commands via Telegram API."""
        commands = [
            BotCommand(command='start', description='Начать работу'),
            BotCommand(command='connect', description='Подключить новую CRM'),
            BotCommand(command='crm_list', description='Список всех CRM'),
            BotCommand(command='switch', description='Переключить активную CRM'),
            BotCommand(command='status', description='Статус текущей CRM'),
            BotCommand(command='openai', description='Настроить OpenAI ключ'),
            BotCommand(command='sync', description='Синхронизировать данные CRM'),
            BotCommand(command='wizard', description='Мастер настройки CRM'),
            BotCommand(command='remove_crm', description='Отключить CRM'),
            BotCommand(command='help', description='Все команды'),
            BotCommand(command='cancel', description='Отменить текущую операцию'),
        ]
        try:
            await self.bot.set_my_commands(commands)
            logger.info('Bot menu commands updated')
        except Exception as e:
            logger.error(f'Failed to set bot commands: {e}')
    
    async def start(self):
        """Start the bot."""
        await self.tenant_manager.init()
        await self.orchestrator.init()
        await self._set_bot_commands()
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
    
    # Start logs server in background with tenant manager reference
    from kommo_mcp.telegram.logs_server import run_logs_server, set_tenant_manager
    set_tenant_manager(tenant_manager)
    logs_port = int(os.getenv('LOGS_PORT', '8765'))
    await run_logs_server(port=logs_port)
    logger.info(f'Logs server started on port {logs_port}')
    
    bot = create_bot(token, tenant_manager, orchestrator)
    await bot.start()
