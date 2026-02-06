"""
Setup Wizard - AI-guided CRM configuration through questionnaire.

Flow:
1. User starts wizard (/wizard or "настроить CRM")
2. AI asks series of questions about business
3. Based on answers, generates detailed setup specification
4. User confirms specification
5. AI executes all configurations automatically
"""

import json
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from enum import Enum

logger = logging.getLogger(__name__)


class BusinessType(Enum):
    """Main business types for CRM templates."""
    SALES_B2B = 'sales_b2b'           # B2B продажи
    SALES_B2C = 'sales_b2c'           # B2C продажи / розница
    SERVICES = 'services'              # Услуги (консалтинг, агентства)
    REAL_ESTATE = 'real_estate'        # Недвижимость
    EDUCATION = 'education'            # Образование / курсы
    ECOMMERCE = 'ecommerce'            # Интернет-магазин
    RECRUITMENT = 'recruitment'        # HR / рекрутинг
    CONSTRUCTION = 'construction'      # Строительство / ремонт
    MEDICAL = 'medical'                # Медицина / клиники
    AUTO = 'auto'                      # Автобизнес
    CUSTOM = 'custom'                  # Другое


@dataclass
class WizardState:
    """Current state of the setup wizard."""
    user_id: int
    step: str = 'start'
    answers: Dict[str, Any] = field(default_factory=dict)
    generated_spec: Optional[str] = None
    confirmed: bool = False
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'WizardState':
        return cls(**data)


# Wizard questions flow
WIZARD_QUESTIONS = {
    'start': {
        'question': '''🧙‍♂️ <b>Мастер настройки CRM</b>

Я помогу настроить вашу CRM под ваш бизнес. Отвечайте на вопросы, и я создам оптимальную конфигурацию.

<b>Какой у вас тип бизнеса?</b>

1️⃣ B2B продажи (корпоративные клиенты)
2️⃣ B2C продажи / розница
3️⃣ Услуги (консалтинг, агентства, фриланс)
4️⃣ Недвижимость
5️⃣ Образование / онлайн-курсы
6️⃣ Интернет-магазин
7️⃣ HR / рекрутинг
8️⃣ Строительство / ремонт
9️⃣ Медицина / клиники
🔟 Автобизнес
0️⃣ Другое (опишите)

<i>Введите номер или опишите своими словами</i>''',
        'field': 'business_type',
        'next': 'business_name',
    },
    
    'business_name': {
        'question': '''<b>Как называется ваша компания/проект?</b>

<i>Это поможет персонализировать настройки</i>''',
        'field': 'business_name',
        'next': 'team_size',
    },
    
    'team_size': {
        'question': '''<b>Сколько человек будет работать в CRM?</b>

1️⃣ Только я (1 человек)
2️⃣ Маленькая команда (2-5 человек)
3️⃣ Средняя команда (6-15 человек)
4️⃣ Большая команда (16+ человек)''',
        'field': 'team_size',
        'next': 'sales_cycle',
    },
    
    'sales_cycle': {
        'question': '''<b>Какой у вас цикл сделки?</b>

1️⃣ Быстрый (до 1 дня) — импульсные покупки
2️⃣ Короткий (1-7 дней) — простые услуги/товары
3️⃣ Средний (1-4 недели) — требует обсуждения
4️⃣ Длинный (1-3 месяца) — сложные B2B продажи
5️⃣ Очень длинный (3+ месяцев) — крупные проекты''',
        'field': 'sales_cycle',
        'next': 'lead_sources',
    },
    
    'lead_sources': {
        'question': '''<b>Откуда приходят ваши клиенты?</b> (можно несколько)

1️⃣ Сайт / лендинг
2️⃣ Телефонные звонки
3️⃣ WhatsApp / Telegram
4️⃣ Социальные сети (Instagram, Facebook, VK)
5️⃣ Email рассылки
6️⃣ Рекомендации / сарафан
7️⃣ Реклама (Яндекс, Google)
8️⃣ Маркетплейсы (Avito, ЦИАН и т.д.)
9️⃣ Выставки / мероприятия
0️⃣ Другое

<i>Введите номера через запятую (например: 1, 3, 4)</i>''',
        'field': 'lead_sources',
        'next': 'deal_stages',
    },
    
    'deal_stages': {
        'question': '''<b>Опишите этапы вашей воронки продаж</b>

Как проходит сделка от первого контакта до закрытия?

<i>Примеры:</i>
• Заявка → Квалификация → КП → Переговоры → Договор → Оплата
• Лид → Показ → Бронь → Сделка
• Обращение → Консультация → Замер → Договор → Работа → Сдача

<i>Опишите своими словами или введите этапы через →</i>''',
        'field': 'deal_stages',
        'next': 'custom_fields',
    },
    
    'custom_fields': {
        'question': '''<b>Какую информацию важно фиксировать по сделкам?</b>

Примеры полей:
• Бюджет клиента
• Срок принятия решения
• Источник рекламы (UTM)
• Тип услуги/товара
• Адрес объекта
• Дата мероприятия

<i>Перечислите важные для вас поля через запятую, или напишите "стандартные"</i>''',
        'field': 'custom_fields',
        'next': 'contact_fields',
    },
    
    'contact_fields': {
        'question': '''<b>Какую информацию собираете о клиентах?</b>

Стандартно: имя, телефон, email

Дополнительно можно:
• Дата рождения (для поздравлений)
• Компания / должность
• Город / адрес
• Предпочтения
• Откуда узнал

<i>Перечислите дополнительные поля или напишите "стандартные"</i>''',
        'field': 'contact_fields',
        'next': 'automations',
    },
    
    'automations': {
        'question': '''<b>Какие автоматизации вам нужны?</b>

1️⃣ Автозадачи при смене этапа
2️⃣ Напоминания о забытых сделках
3️⃣ Уведомления руководителю о крупных сделках
4️⃣ Автоматическое распределение заявок
5️⃣ Эскалация просроченных задач
6️⃣ Авто-письма/сообщения клиентам
7️⃣ Пока не нужны автоматизации

<i>Введите номера через запятую или опишите свои</i>''',
        'field': 'automations',
        'next': 'additional',
    },
    
    'additional': {
        'question': '''<b>Есть ли особые требования или пожелания?</b>

Например:
• Интеграция с конкретным сервисом
• Особая логика работы
• Специфика вашей ниши

<i>Опишите или напишите "нет"</i>''',
        'field': 'additional',
        'next': 'generate_spec',
    },
}


# Business type templates with default configurations
BUSINESS_TEMPLATES = {
    BusinessType.SALES_B2B: {
        'name': 'B2B Продажи',
        'pipelines': [
            {
                'name': 'Продажи B2B',
                'stages': ['Новая заявка', 'Квалификация', 'Презентация', 'КП отправлено', 'Переговоры', 'Согласование договора', 'Счёт выставлен', 'Успешно', 'Закрыто и не реализовано'],
            }
        ],
        'lead_fields': ['Бюджет', 'Срок принятия решения', 'ЛПР', 'Количество сотрудников', 'Отрасль'],
        'contact_fields': ['Должность', 'Компания', 'День рождения'],
    },
    BusinessType.SALES_B2C: {
        'name': 'B2C Продажи',
        'pipelines': [
            {
                'name': 'Розничные продажи',
                'stages': ['Новый лид', 'В обработке', 'Консультация', 'Ожидает оплаты', 'Оплачено', 'Доставка', 'Успешно', 'Отказ'],
            }
        ],
        'lead_fields': ['Товар/услуга', 'Способ оплаты', 'Адрес доставки', 'Промокод'],
        'contact_fields': ['День рождения', 'Предпочтения'],
    },
    BusinessType.SERVICES: {
        'name': 'Услуги',
        'pipelines': [
            {
                'name': 'Проекты',
                'stages': ['Заявка', 'Брифинг', 'КП', 'Согласование', 'Договор', 'В работе', 'Сдача', 'Успешно', 'Отказ'],
            }
        ],
        'lead_fields': ['Тип услуги', 'Бюджет', 'Дедлайн', 'Объём работ'],
        'contact_fields': ['Компания', 'Сфера деятельности'],
    },
    BusinessType.REAL_ESTATE: {
        'name': 'Недвижимость',
        'pipelines': [
            {
                'name': 'Продажа недвижимости',
                'stages': ['Новый запрос', 'Квалификация', 'Подбор объектов', 'Показы', 'Переговоры', 'Бронь', 'Сделка', 'Успешно', 'Отказ'],
            }
        ],
        'lead_fields': ['Тип недвижимости', 'Бюджет от', 'Бюджет до', 'Район', 'Площадь', 'Срочность'],
        'contact_fields': ['Семейное положение', 'Цель покупки'],
    },
    BusinessType.EDUCATION: {
        'name': 'Образование',
        'pipelines': [
            {
                'name': 'Набор на курс',
                'stages': ['Заявка', 'Консультация', 'Пробный урок', 'Думает', 'Оплата', 'Учится', 'Выпускник', 'Отказ'],
            }
        ],
        'lead_fields': ['Курс', 'Формат обучения', 'Уровень подготовки', 'Цель обучения'],
        'contact_fields': ['Возраст', 'Образование', 'Профессия'],
    },
    BusinessType.ECOMMERCE: {
        'name': 'Интернет-магазин',
        'pipelines': [
            {
                'name': 'Заказы',
                'stages': ['Новый заказ', 'Подтверждение', 'Сборка', 'Отправлен', 'Доставлен', 'Успешно', 'Возврат', 'Отмена'],
            }
        ],
        'lead_fields': ['Номер заказа', 'Сумма заказа', 'Способ доставки', 'Трек-номер'],
        'contact_fields': ['Адрес доставки', 'Предпочтения'],
    },
    BusinessType.RECRUITMENT: {
        'name': 'HR / Рекрутинг',
        'pipelines': [
            {
                'name': 'Подбор персонала',
                'stages': ['Новое резюме', 'Скрининг', 'HR интервью', 'Тех. интервью', 'Финал', 'Оффер', 'Принят', 'Отказ'],
            }
        ],
        'lead_fields': ['Вакансия', 'Зарплатные ожидания', 'Опыт работы', 'Навыки'],
        'contact_fields': ['Текущая компания', 'Должность', 'LinkedIn'],
    },
    BusinessType.CONSTRUCTION: {
        'name': 'Строительство / Ремонт',
        'pipelines': [
            {
                'name': 'Проекты',
                'stages': ['Заявка', 'Выезд на замер', 'Смета', 'Согласование', 'Договор', 'Работы', 'Приёмка', 'Успешно', 'Отказ'],
            }
        ],
        'lead_fields': ['Тип работ', 'Адрес объекта', 'Площадь', 'Бюджет', 'Срок'],
        'contact_fields': ['Тип клиента', 'Адрес'],
    },
    BusinessType.MEDICAL: {
        'name': 'Медицина',
        'pipelines': [
            {
                'name': 'Пациенты',
                'stages': ['Запись', 'Подтверждение', 'Приём', 'Лечение', 'Контроль', 'Завершено', 'Отмена'],
            }
        ],
        'lead_fields': ['Услуга', 'Врач', 'Дата приёма', 'Симптомы'],
        'contact_fields': ['Дата рождения', 'Пол', 'Противопоказания'],
    },
    BusinessType.AUTO: {
        'name': 'Автобизнес',
        'pipelines': [
            {
                'name': 'Продажа авто',
                'stages': ['Заявка', 'Консультация', 'Тест-драйв', 'Подбор', 'КП', 'Сделка', 'Выдача', 'Успешно', 'Отказ'],
            }
        ],
        'lead_fields': ['Марка/модель', 'Бюджет', 'Новый/БУ', 'Trade-in'],
        'contact_fields': ['Текущий авто', 'Права категории'],
    },
}


class SetupWizard:
    """AI-guided CRM setup wizard."""
    
    # Store wizard states per user
    _states: Dict[int, WizardState] = {}
    
    def __init__(self, ai_chat):
        """Initialize wizard with AI chat instance for executing setup."""
        self.ai_chat = ai_chat
    
    def start(self, user_id: int) -> str:
        """Start the wizard for a user."""
        self._states[user_id] = WizardState(user_id=user_id, step='start')
        return WIZARD_QUESTIONS['start']['question']
    
    def is_active(self, user_id: int) -> bool:
        """Check if wizard is active for user."""
        return user_id in self._states and not self._states[user_id].confirmed
    
    def get_state(self, user_id: int) -> Optional[WizardState]:
        """Get current wizard state."""
        return self._states.get(user_id)
    
    async def process_answer(self, user_id: int, answer: str) -> str:
        """Process user's answer and return next question or spec."""
        state = self._states.get(user_id)
        if not state:
            return self.start(user_id)
        
        current_step = state.step
        
        # Handle confirmation step
        if current_step == 'confirm':
            return await self._handle_confirmation(user_id, answer)
        
        # Handle generate_spec step
        if current_step == 'generate_spec':
            return await self._generate_specification(user_id)
        
        # Save answer
        question_config = WIZARD_QUESTIONS.get(current_step)
        if question_config:
            field = question_config.get('field')
            if field:
                state.answers[field] = self._parse_answer(current_step, answer)
            
            # Move to next step
            next_step = question_config.get('next')
            state.step = next_step
            
            # If next is generate_spec, generate it
            if next_step == 'generate_spec':
                return await self._generate_specification(user_id)
            
            # Return next question
            next_question = WIZARD_QUESTIONS.get(next_step, {}).get('question')
            if next_question:
                return next_question
        
        return '❌ Ошибка в wizard. Попробуйте /wizard заново.'
    
    def _parse_answer(self, step: str, answer: str) -> Any:
        """Parse answer based on step type."""
        answer = answer.strip()
        
        # Parse business type
        if step == 'start':
            type_map = {
                '1': BusinessType.SALES_B2B,
                '2': BusinessType.SALES_B2C,
                '3': BusinessType.SERVICES,
                '4': BusinessType.REAL_ESTATE,
                '5': BusinessType.EDUCATION,
                '6': BusinessType.ECOMMERCE,
                '7': BusinessType.RECRUITMENT,
                '8': BusinessType.CONSTRUCTION,
                '9': BusinessType.MEDICAL,
                '10': BusinessType.AUTO,
                '0': BusinessType.CUSTOM,
            }
            if answer in type_map:
                return type_map[answer].value
            # Try to match by keywords
            answer_lower = answer.lower()
            if any(k in answer_lower for k in ['b2b', 'корпоратив', 'оптов']):
                return BusinessType.SALES_B2B.value
            if any(k in answer_lower for k in ['b2c', 'розниц', 'магазин']):
                return BusinessType.SALES_B2C.value
            if any(k in answer_lower for k in ['услуг', 'агент', 'консалт', 'фриланс']):
                return BusinessType.SERVICES.value
            if any(k in answer_lower for k in ['недвиж', 'квартир', 'дом']):
                return BusinessType.REAL_ESTATE.value
            if any(k in answer_lower for k in ['обуч', 'курс', 'школ', 'образ']):
                return BusinessType.EDUCATION.value
            if any(k in answer_lower for k in ['интернет-магазин', 'ecommerce', 'онлайн магазин']):
                return BusinessType.ECOMMERCE.value
            if any(k in answer_lower for k in ['hr', 'рекрут', 'персонал', 'кадр']):
                return BusinessType.RECRUITMENT.value
            if any(k in answer_lower for k in ['строит', 'ремонт', 'отделк']):
                return BusinessType.CONSTRUCTION.value
            if any(k in answer_lower for k in ['медиц', 'клиник', 'врач', 'здоров']):
                return BusinessType.MEDICAL.value
            if any(k in answer_lower for k in ['авто', 'машин', 'автосалон']):
                return BusinessType.AUTO.value
            return answer  # Custom description
        
        # Parse team size
        if step == 'team_size':
            size_map = {'1': '1', '2': '2-5', '3': '6-15', '4': '16+'}
            return size_map.get(answer, answer)
        
        # Parse sales cycle
        if step == 'sales_cycle':
            cycle_map = {
                '1': 'быстрый (до 1 дня)',
                '2': 'короткий (1-7 дней)',
                '3': 'средний (1-4 недели)',
                '4': 'длинный (1-3 месяца)',
                '5': 'очень длинный (3+ месяцев)',
            }
            return cycle_map.get(answer, answer)
        
        # Parse multi-select (lead_sources, automations)
        if step in ['lead_sources', 'automations']:
            sources_map = {
                'lead_sources': {
                    '1': 'Сайт/лендинг', '2': 'Звонки', '3': 'Мессенджеры',
                    '4': 'Соцсети', '5': 'Email', '6': 'Рекомендации',
                    '7': 'Реклама', '8': 'Маркетплейсы', '9': 'Мероприятия', '0': 'Другое',
                },
                'automations': {
                    '1': 'Автозадачи', '2': 'Напоминания', '3': 'Уведомления руководителю',
                    '4': 'Распределение заявок', '5': 'Эскалация', '6': 'Авто-сообщения', '7': 'Не нужны',
                },
            }
            mapping = sources_map.get(step, {})
            # Parse comma-separated numbers
            parts = [p.strip() for p in answer.replace(',', ' ').split()]
            result = []
            for p in parts:
                if p in mapping:
                    result.append(mapping[p])
                else:
                    result.append(p)
            return result if result else [answer]
        
        return answer
    
    async def _generate_specification(self, user_id: int) -> str:
        """Generate setup specification based on answers."""
        state = self._states.get(user_id)
        if not state:
            return '❌ Ошибка: состояние не найдено'
        
        answers = state.answers
        
        # Get business template if available
        business_type_str = answers.get('business_type', '')
        template = None
        for bt in BusinessType:
            if bt.value == business_type_str:
                template = BUSINESS_TEMPLATES.get(bt)
                break
        
        # Build specification
        spec = self._build_specification(answers, template)
        state.generated_spec = spec
        state.step = 'confirm'
        
        response = f'''📋 <b>Техническое задание на настройку CRM</b>

{spec}

---

<b>Всё верно?</b> Напишите:
• <b>Да</b> — начать настройку
• <b>Нет</b> — начать заново
• Или опишите, что изменить'''
        
        return response
    
    def _build_specification(self, answers: Dict, template: Optional[Dict]) -> str:
        """Build detailed specification text."""
        lines = []
        
        # Company info
        business_name = answers.get('business_name', 'Компания')
        business_type = answers.get('business_type', 'Не указан')
        team_size = answers.get('team_size', 'Не указан')
        
        lines.append(f'<b>🏢 Компания:</b> {business_name}')
        lines.append(f'<b>📊 Тип бизнеса:</b> {business_type}')
        lines.append(f'<b>👥 Размер команды:</b> {team_size}')
        lines.append(f'<b>⏱ Цикл сделки:</b> {answers.get("sales_cycle", "Не указан")}')
        lines.append('')
        
        # Lead sources
        sources = answers.get('lead_sources', [])
        if sources:
            if isinstance(sources, list):
                lines.append(f'<b>📥 Источники лидов:</b> {", ".join(sources)}')
            else:
                lines.append(f'<b>📥 Источники лидов:</b> {sources}')
        lines.append('')
        
        # Pipeline and stages
        lines.append('<b>🔄 ВОРОНКА ПРОДАЖ:</b>')
        deal_stages = answers.get('deal_stages', '')
        if deal_stages and deal_stages.lower() not in ['стандартные', 'стандартная', 'по умолчанию']:
            # Parse user's stages
            if '→' in deal_stages:
                stages = [s.strip() for s in deal_stages.split('→')]
            elif ',' in deal_stages:
                stages = [s.strip() for s in deal_stages.split(',')]
            else:
                stages = [deal_stages]
            
            # Add standard closing stages if not present
            closing_keywords = ['успех', 'закрыт', 'отказ', 'реализ', 'оплач']
            has_closing = any(any(k in s.lower() for k in closing_keywords) for s in stages)
            if not has_closing:
                stages.extend(['Успешно реализовано', 'Закрыто и не реализовано'])
            
            lines.append(f'  Воронка: {business_name}')
            for i, stage in enumerate(stages, 1):
                lines.append(f'    {i}. {stage}')
        elif template:
            # Use template stages
            for pipeline in template.get('pipelines', []):
                lines.append(f'  Воронка: {pipeline["name"]}')
                for i, stage in enumerate(pipeline['stages'], 1):
                    lines.append(f'    {i}. {stage}')
        else:
            lines.append('  Стандартная воронка продаж')
        lines.append('')
        
        # Custom fields for leads
        lines.append('<b>📝 ПОЛЯ СДЕЛОК:</b>')
        custom_fields = answers.get('custom_fields', '')
        if custom_fields and custom_fields.lower() not in ['стандартные', 'стандартная', 'нет']:
            fields = [f.strip() for f in custom_fields.split(',')]
            for f in fields:
                lines.append(f'  • {f}')
        elif template:
            for f in template.get('lead_fields', []):
                lines.append(f'  • {f}')
        else:
            lines.append('  • Бюджет')
            lines.append('  • Источник')
        lines.append('')
        
        # Contact fields
        lines.append('<b>👤 ПОЛЯ КОНТАКТОВ:</b>')
        lines.append('  • Имя, Телефон, Email (стандартные)')
        contact_fields = answers.get('contact_fields', '')
        if contact_fields and contact_fields.lower() not in ['стандартные', 'стандартная', 'нет']:
            fields = [f.strip() for f in contact_fields.split(',')]
            for f in fields:
                lines.append(f'  • {f}')
        elif template:
            for f in template.get('contact_fields', []):
                lines.append(f'  • {f}')
        lines.append('')
        
        # Automations
        automations = answers.get('automations', [])
        if automations and automations != ['Не нужны']:
            lines.append('<b>⚡ АВТОМАТИЗАЦИИ:</b>')
            if isinstance(automations, list):
                for a in automations:
                    if a != 'Не нужны':
                        lines.append(f'  • {a}')
            else:
                lines.append(f'  • {automations}')
            lines.append('')
        
        # Additional requirements
        additional = answers.get('additional', '')
        if additional and additional.lower() not in ['нет', 'нету', '-', 'не']:
            lines.append('<b>📌 ДОПОЛНИТЕЛЬНО:</b>')
            lines.append(f'  {additional}')
        
        return '\n'.join(lines)
    
    async def _handle_confirmation(self, user_id: int, answer: str) -> str:
        """Handle user's confirmation of specification."""
        state = self._states.get(user_id)
        if not state:
            return '❌ Ошибка: состояние не найдено'
        
        answer_lower = answer.lower().strip()
        
        # User confirms
        if answer_lower in ['да', 'yes', 'ок', 'ok', 'подтверждаю', 'верно', 'всё верно', 'все верно', '+']:
            state.confirmed = True
            return await self._execute_setup(user_id)
        
        # User wants to restart
        if answer_lower in ['нет', 'no', 'заново', 'сначала', 'restart']:
            return self.start(user_id)
        
        # User wants to modify - use AI to understand and adjust
        return await self._modify_specification(user_id, answer)
    
    async def _modify_specification(self, user_id: int, modification: str) -> str:
        """Use AI to modify specification based on user's request."""
        state = self._states.get(user_id)
        if not state or not state.generated_spec:
            return self.start(user_id)
        
        # For now, just restart - in future, use AI to modify
        # TODO: Use AI to intelligently modify the spec
        return f'''Понял, вы хотите изменить: {modification}

Пока что функция редактирования в разработке. 
Давайте начнём заново с учётом ваших пожеланий.

{self.start(user_id)}'''
    
    async def _execute_setup(self, user_id: int) -> str:
        """Execute the CRM setup based on specification."""
        state = self._states.get(user_id)
        if not state:
            return '❌ Ошибка: состояние не найдено'
        
        # Build setup prompt from specification and store it
        setup_prompt = self._build_setup_prompt(state.answers)
        state.setup_prompt = setup_prompt
        
        # Don't delete state yet - bot.py will call get_setup_prompt and then we clear
        
        # Return message that will be shown to user
        return f'''🚀 <b>Начинаю настройку CRM...</b>

{setup_prompt}

<i>Это может занять несколько секунд...</i>'''
    
    def _build_setup_prompt(self, answers: Dict) -> str:
        """Build AI prompt for executing setup."""
        business_name = answers.get('business_name', 'Основная')
        business_type = answers.get('business_type', '')
        
        # Get stages
        deal_stages = answers.get('deal_stages', '')
        stages_str = ''
        if deal_stages and deal_stages.lower() not in ['стандартные', 'стандартная']:
            if '→' in deal_stages:
                stages = [s.strip() for s in deal_stages.split('→')]
            elif ',' in deal_stages:
                stages = [s.strip() for s in deal_stages.split(',')]
            else:
                stages = [deal_stages]
            stages_str = ', '.join(stages)
        else:
            # Use template stages
            for bt in BusinessType:
                if bt.value == business_type:
                    template = BUSINESS_TEMPLATES.get(bt)
                    if template and template.get('pipelines'):
                        stages_str = ', '.join(template['pipelines'][0].get('stages', []))
                    break
        
        # Get custom fields
        custom_fields = answers.get('custom_fields', '')
        fields_str = ''
        if custom_fields and custom_fields.lower() not in ['стандартные', 'стандартная', 'нет']:
            fields_str = custom_fields
        else:
            for bt in BusinessType:
                if bt.value == business_type:
                    template = BUSINESS_TEMPLATES.get(bt)
                    if template:
                        fields_str = ', '.join(template.get('lead_fields', []))
                    break
        
        prompt_parts = [f'Создай воронку "{business_name}"']
        if stages_str:
            prompt_parts.append(f'со стадиями: {stages_str}')
        if fields_str:
            prompt_parts.append(f'и кастомными полями для сделок: {fields_str}')
        
        return ' '.join(prompt_parts)
    
    def get_setup_prompt(self, user_id: int) -> Optional[str]:
        """Get the setup prompt for execution after wizard completion."""
        state = self._states.get(user_id)
        if state and state.confirmed:
            prompt = getattr(state, 'setup_prompt', None) or self._build_setup_prompt(state.answers)
            # Clear wizard state after getting prompt
            del self._states[user_id]
            return prompt
        return None
    
    def cancel(self, user_id: int) -> str:
        """Cancel the wizard."""
        if user_id in self._states:
            del self._states[user_id]
        return '❌ Мастер настройки отменён. Используйте /wizard чтобы начать заново.'


# Global wizard instance
_wizard: Optional[SetupWizard] = None


def get_wizard(ai_chat=None) -> SetupWizard:
    """Get or create the global wizard instance."""
    global _wizard
    if _wizard is None:
        _wizard = SetupWizard(ai_chat)
    elif ai_chat:
        _wizard.ai_chat = ai_chat
    return _wizard
