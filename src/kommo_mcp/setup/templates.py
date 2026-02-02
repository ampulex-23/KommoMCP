"""Pipeline templates for different business types."""

# Stage colors
COLORS = {
    'gray': '#d5d8db',
    'blue': '#99ccff',
    'green': '#99e599',
    'yellow': '#fffeb2',
    'orange': '#ffcc66',
    'red': '#ffb2b2',
    'purple': '#ccc8f9',
    'pink': '#f9c8d9',
}


# Template: Sales (B2B/B2C)
SALES_PIPELINE = {
    'name': 'Продажи',
    'stages': [
        {'name': 'Новая заявка', 'sort': 10, 'color': COLORS['gray']},
        {'name': 'Квалификация', 'sort': 20, 'color': COLORS['blue']},
        {'name': 'Презентация', 'sort': 30, 'color': COLORS['yellow']},
        {'name': 'Коммерческое предложение', 'sort': 40, 'color': COLORS['orange']},
        {'name': 'Переговоры', 'sort': 50, 'color': COLORS['purple']},
        {'name': 'Согласование договора', 'sort': 60, 'color': COLORS['pink']},
        {'name': 'Оплата', 'sort': 70, 'color': COLORS['green']},
    ],
    'fields': [
        {'name': 'Источник', 'type': 'select', 'enums': [
            {'value': 'Сайт', 'sort': 1},
            {'value': 'Звонок', 'sort': 2},
            {'value': 'Рекомендация', 'sort': 3},
            {'value': 'Реклама', 'sort': 4},
        ]},
        {'name': 'Бюджет клиента', 'type': 'numeric'},
        {'name': 'Дата следующего контакта', 'type': 'date'},
    ],
    'sources': ['Сайт', 'Телефон', 'Email', 'Соцсети', 'Рекомендация'],
}


# Template: Services (автосервис, салон, клиника)
SERVICES_PIPELINE = {
    'name': 'Услуги',
    'stages': [
        {'name': 'Заявка', 'sort': 10, 'color': COLORS['gray']},
        {'name': 'Консультация', 'sort': 20, 'color': COLORS['blue']},
        {'name': 'Диагностика', 'sort': 30, 'color': COLORS['yellow']},
        {'name': 'Согласование', 'sort': 40, 'color': COLORS['orange']},
        {'name': 'В работе', 'sort': 50, 'color': COLORS['purple']},
        {'name': 'Контроль качества', 'sort': 60, 'color': COLORS['pink']},
        {'name': 'Выдача/Завершение', 'sort': 70, 'color': COLORS['green']},
    ],
    'fields': [
        {'name': 'Тип услуги', 'type': 'select', 'enums': [
            {'value': 'Ремонт', 'sort': 1},
            {'value': 'Обслуживание', 'sort': 2},
            {'value': 'Консультация', 'sort': 3},
        ]},
        {'name': 'Срочность', 'type': 'select', 'enums': [
            {'value': 'Обычная', 'sort': 1},
            {'value': 'Срочная', 'sort': 2},
            {'value': 'Экстренная', 'sort': 3},
        ]},
        {'name': 'Дата записи', 'type': 'date'},
    ],
    'sources': ['Сайт', 'Телефон', 'Визит', 'Рекомендация'],
}


# Template: Rental (прокат, аренда)
RENTAL_PIPELINE = {
    'name': 'Прокат',
    'stages': [
        {'name': 'Заявка', 'sort': 10, 'color': COLORS['gray']},
        {'name': 'Подбор', 'sort': 20, 'color': COLORS['blue']},
        {'name': 'Бронирование', 'sort': 30, 'color': COLORS['yellow']},
        {'name': 'Оплата', 'sort': 40, 'color': COLORS['orange']},
        {'name': 'Выдача', 'sort': 50, 'color': COLORS['purple']},
        {'name': 'В прокате', 'sort': 60, 'color': COLORS['pink']},
        {'name': 'Возврат', 'sort': 70, 'color': COLORS['green']},
    ],
    'fields': [
        {'name': 'Дата начала', 'type': 'date'},
        {'name': 'Дата окончания', 'type': 'date'},
        {'name': 'Залог', 'type': 'numeric'},
        {'name': 'Оборудование', 'type': 'text'},
    ],
    'sources': ['Сайт', 'Телефон', 'Визит'],
}


# Template: Real Estate (недвижимость)
REALESTATE_PIPELINE = {
    'name': 'Недвижимость',
    'stages': [
        {'name': 'Новый запрос', 'sort': 10, 'color': COLORS['gray']},
        {'name': 'Подбор объектов', 'sort': 20, 'color': COLORS['blue']},
        {'name': 'Показы', 'sort': 30, 'color': COLORS['yellow']},
        {'name': 'Переговоры', 'sort': 40, 'color': COLORS['orange']},
        {'name': 'Бронирование', 'sort': 50, 'color': COLORS['purple']},
        {'name': 'Документы', 'sort': 60, 'color': COLORS['pink']},
        {'name': 'Сделка', 'sort': 70, 'color': COLORS['green']},
    ],
    'fields': [
        {'name': 'Тип сделки', 'type': 'select', 'enums': [
            {'value': 'Покупка', 'sort': 1},
            {'value': 'Аренда', 'sort': 2},
            {'value': 'Продажа', 'sort': 3},
        ]},
        {'name': 'Бюджет от', 'type': 'numeric'},
        {'name': 'Бюджет до', 'type': 'numeric'},
        {'name': 'Район', 'type': 'text'},
    ],
    'sources': ['Сайт', 'Авито', 'ЦИАН', 'Рекомендация', 'Звонок'],
}


# Template: Education (курсы, обучение)
EDUCATION_PIPELINE = {
    'name': 'Обучение',
    'stages': [
        {'name': 'Заявка', 'sort': 10, 'color': COLORS['gray']},
        {'name': 'Консультация', 'sort': 20, 'color': COLORS['blue']},
        {'name': 'Пробный урок', 'sort': 30, 'color': COLORS['yellow']},
        {'name': 'Выбор программы', 'sort': 40, 'color': COLORS['orange']},
        {'name': 'Оплата', 'sort': 50, 'color': COLORS['purple']},
        {'name': 'Обучение', 'sort': 60, 'color': COLORS['pink']},
        {'name': 'Выпуск', 'sort': 70, 'color': COLORS['green']},
    ],
    'fields': [
        {'name': 'Курс', 'type': 'select', 'enums': [
            {'value': 'Базовый', 'sort': 1},
            {'value': 'Продвинутый', 'sort': 2},
            {'value': 'Индивидуальный', 'sort': 3},
        ]},
        {'name': 'Формат', 'type': 'select', 'enums': [
            {'value': 'Онлайн', 'sort': 1},
            {'value': 'Офлайн', 'sort': 2},
            {'value': 'Гибрид', 'sort': 3},
        ]},
    ],
    'sources': ['Сайт', 'Соцсети', 'Рекомендация', 'Реклама'],
}


# Template: E-commerce (интернет-магазин)
ECOMMERCE_PIPELINE = {
    'name': 'Заказы',
    'stages': [
        {'name': 'Новый заказ', 'sort': 10, 'color': COLORS['gray']},
        {'name': 'Подтверждение', 'sort': 20, 'color': COLORS['blue']},
        {'name': 'Оплата', 'sort': 30, 'color': COLORS['yellow']},
        {'name': 'Сборка', 'sort': 40, 'color': COLORS['orange']},
        {'name': 'Доставка', 'sort': 50, 'color': COLORS['purple']},
        {'name': 'Получен', 'sort': 60, 'color': COLORS['green']},
    ],
    'fields': [
        {'name': 'Способ доставки', 'type': 'select', 'enums': [
            {'value': 'Самовывоз', 'sort': 1},
            {'value': 'Курьер', 'sort': 2},
            {'value': 'Почта', 'sort': 3},
            {'value': 'СДЭК', 'sort': 4},
        ]},
        {'name': 'Трек-номер', 'type': 'text'},
        {'name': 'Адрес доставки', 'type': 'textarea'},
    ],
    'sources': ['Сайт', 'Маркетплейс', 'Соцсети', 'Телефон'],
}


# All templates registry
TEMPLATES = {
    'sales': SALES_PIPELINE,
    'services': SERVICES_PIPELINE,
    'rental': RENTAL_PIPELINE,
    'realestate': REALESTATE_PIPELINE,
    'education': EDUCATION_PIPELINE,
    'ecommerce': ECOMMERCE_PIPELINE,
}


def get_template(name: str) -> dict | None:
    """Get pipeline template by name."""
    return TEMPLATES.get(name.lower())


def list_templates() -> list[dict]:
    """List all available templates."""
    return [
        {'id': 'sales', 'name': 'Продажи', 'description': 'B2B/B2C продажи с полным циклом'},
        {'id': 'services', 'name': 'Услуги', 'description': 'Автосервис, салон, клиника'},
        {'id': 'rental', 'name': 'Прокат', 'description': 'Аренда и прокат оборудования'},
        {'id': 'realestate', 'name': 'Недвижимость', 'description': 'Продажа и аренда недвижимости'},
        {'id': 'education', 'name': 'Обучение', 'description': 'Курсы и образовательные программы'},
        {'id': 'ecommerce', 'name': 'Интернет-магазин', 'description': 'Обработка заказов'},
    ]
