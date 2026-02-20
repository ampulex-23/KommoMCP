// KommoMCP Business Presentation
// Compile: typst compile presentation.typ

#set page(
  width: 254mm,
  height: 190.5mm,
  margin: (x: 20mm, y: 16mm),
  fill: white,
)

#set text(
  font: "Segoe UI",
  size: 12pt,
  fill: rgb("#1a1a2e"),
)

// Color palette
#let primary = rgb("#0f3460")
#let accent = rgb("#e94560")
#let light-bg = rgb("#f8f9fa")
#let dark-bg = rgb("#16213e")
#let success = rgb("#00b894")
#let muted = rgb("#6c757d")
#let blue-light = rgb("#e3f2fd")
#let green-light = rgb("#e8f5e9")
#let orange-light = rgb("#fff3e0")
#let pink-light = rgb("#fce4ec")
#let purple-light = rgb("#ede7f6")

// ── Decorative elements ──

// Accent bar at top of slide
#let top-bar(color: accent) = {
  place(top + left, dx: -20mm, dy: -16mm,
    rect(width: 294mm, height: 4pt, fill: color)
  )
}

// Corner decoration
#let corner-dot(color: accent, dx-val: 0mm, dy-val: 0mm) = {
  place(top + right, dx: dx-val, dy: dy-val,
    circle(radius: 24pt, fill: color.lighten(85%))
  )
}

// Progress bar component
#let progress-bar(pct, color: accent, width: 100%) = {
  box(width: width, height: 6pt, radius: 3pt, fill: rgb("#e0e0e0"), clip: true)[
    #box(width: pct, height: 6pt, radius: 3pt, fill: color)
  ]
}

// Badge / pill
#let badge(content, bg: accent, fg: white) = {
  box(inset: (x: 8pt, y: 3pt), radius: 10pt, fill: bg)[
    #text(size: 9pt, weight: "bold", fill: fg)[#content]
  ]
}

// Slide template
#let slide(title: none, subtitle: none, bg: white, bar-color: accent, body) = {
  set page(fill: bg)
  top-bar(color: bar-color)
  corner-dot(color: bar-color, dx-val: -8mm, dy-val: 12mm)
  if title != none {
    block(width: 100%)[
      #text(size: 24pt, weight: "bold", fill: primary)[#title]
      #if subtitle != none {
        v(2pt)
        text(size: 13pt, fill: muted)[#subtitle]
      }
      #v(4pt)
      #line(length: 50pt, stroke: 2.5pt + bar-color)
    ]
    v(8pt)
  }
  body
  pagebreak(weak: true)
}

// Metric box with icon ring
#let metric(value, label, icon: "●", color: accent) = {
  box(
    width: 100%,
    inset: 10pt,
    radius: 10pt,
    fill: white,
    stroke: 1pt + color.lighten(60%),
  )[
    #align(center)[
      #box(inset: 4pt, radius: 16pt, fill: color.lighten(85%))[
        #text(size: 14pt)[#icon]
      ]
      #v(4pt)
      #text(size: 24pt, weight: "bold", fill: color)[#value]\
      #text(size: 9pt, fill: muted)[#label]
    ]
  ]
}

// Feature card
#let feature-card(icon, title, desc, bg: light-bg) = {
  box(inset: 10pt, radius: 8pt, fill: bg, width: 100%)[
    #text(size: 14pt)[#icon] #text(size: 11pt, weight: "bold")[#title]\
    #text(size: 10pt, fill: muted)[#desc]
  ]
}

// ============================================================
// SLIDE 1: Title
// ============================================================
#set page(fill: dark-bg)
#place(top + left, dx: -20mm, dy: -16mm,
  rect(width: 294mm, height: 4pt, fill: accent)
)
// Decorative circles
#place(top + right, dx: -10mm, dy: 20mm,
  circle(radius: 40pt, fill: rgb("#1a1a3e"))
)
#place(top + right, dx: -25mm, dy: 50mm,
  circle(radius: 20pt, fill: accent.lighten(80%))
)
#place(bottom + left, dx: 10mm, dy: -20mm,
  circle(radius: 30pt, fill: rgb("#1a1a3e"))
)
#v(14mm)
#align(center)[
  // Logo circle
  #box(inset: 12pt, radius: 28pt, fill: accent)[
    #text(size: 22pt, weight: "bold", fill: white)[K]
  ]
  #v(8pt)
  #text(size: 40pt, weight: "bold", fill: white)[KommoMCP]
  #v(2pt)
  #text(size: 17pt, fill: rgb("#a0a0c0"))[AI-ассистент для CRM Kommo]
  #v(10pt)
  #line(length: 70pt, stroke: 2pt + accent)
  #v(10pt)
  #text(size: 13pt, fill: rgb("#8888aa"))[
    Telegram-бот, который управляет вашей CRM через естественный язык
  ]
  #v(18pt)
  #grid(
    columns: (1fr, 1fr, 1fr, 1fr),
    gutter: 14pt,
    box(inset: 10pt, radius: 8pt, fill: rgb("#1a1a3e"), stroke: 0.5pt + rgb("#2a2a4e"))[
      #align(center)[
        #text(size: 22pt, weight: "bold", fill: accent)[54]\
        #text(size: 9pt, fill: rgb("#8888aa"))[инструмента]
      ]
    ],
    box(inset: 10pt, radius: 8pt, fill: rgb("#1a1a3e"), stroke: 0.5pt + rgb("#2a2a4e"))[
      #align(center)[
        #text(size: 22pt, weight: "bold", fill: success)[\<2ms]\
        #text(size: 9pt, fill: rgb("#8888aa"))[планирование]
      ]
    ],
    box(inset: 10pt, radius: 8pt, fill: rgb("#1a1a3e"), stroke: 0.5pt + rgb("#2a2a4e"))[
      #align(center)[
        #text(size: 22pt, weight: "bold", fill: accent)[SaaS]\
        #text(size: 9pt, fill: rgb("#8888aa"))[мульти-тенант]
      ]
    ],
    box(inset: 10pt, radius: 8pt, fill: rgb("#1a1a3e"), stroke: 0.5pt + rgb("#2a2a4e"))[
      #align(center)[
        #text(size: 22pt, weight: "bold", fill: success)[MCP]\
        #text(size: 9pt, fill: rgb("#8888aa"))[протокол]
      ]
    ],
  )
]
#pagebreak()

// ============================================================
// SLIDE 2: Problem
// ============================================================
#slide(title: "Проблема", subtitle: "Почему CRM-менеджеры теряют время", bar-color: accent)[
  #grid(
    columns: (1fr, 14pt, 1fr),
    [
      #text(size: 13pt, weight: "bold", fill: accent)[⚠️ Боль бизнеса]
      #v(6pt)
      // Pain point cards with severity bars
      #box(inset: 8pt, radius: 6pt, fill: pink-light, width: 100%)[
        #text(size: 11pt)[*70% времени* уходит на рутину в CRM]
        #v(3pt)
        #progress-bar(70%, color: accent)
      ]
      #v(4pt)
      #box(inset: 8pt, radius: 6pt, fill: pink-light, width: 100%)[
        #text(size: 11pt)[*Аналитика* — экспорт в Excel, часы работы]
        #v(3pt)
        #progress-bar(60%, color: accent)
      ]
      #v(4pt)
      #box(inset: 8pt, radius: 6pt, fill: pink-light, width: 100%)[
        #text(size: 11pt)[*Обучение* новых сотрудников — недели]
        #v(3pt)
        #progress-bar(50%, color: accent)
      ]
      #v(4pt)
      #box(inset: 8pt, radius: 6pt, fill: pink-light, width: 100%)[
        #text(size: 11pt)[*Отчёты* устаревают за день]
        #v(3pt)
        #progress-bar(45%, color: accent)
      ]
    ],
    // Visual separator
    align(center + horizon)[
      #line(length: 100%, angle: 90deg, stroke: 1.5pt + rgb("#dee2e6"))
    ],
    [
      #text(size: 13pt, weight: "bold", fill: success)[✅ Решение: KommoMCP]
      #v(6pt)

      #box(inset: 8pt, radius: 6pt, fill: green-light, width: 100%)[
        #text(size: 11pt)[
          💬 *«Покажи аналитику по воронкам»*\
          → Полный отчёт за *10 секунд*
        ]
      ]
      #v(4pt)
      #box(inset: 8pt, radius: 6pt, fill: green-light, width: 100%)[
        #text(size: 11pt)[
          💬 *«Перемести сделку в Переговоры»*\
          → Бот сам найдёт воронку
        ]
      ]
      #v(4pt)
      #box(inset: 8pt, radius: 6pt, fill: green-light, width: 100%)[
        #text(size: 11pt)[
          💬 *«Кто из менеджеров отстаёт?»*\
          → Мгновенный анализ
        ]
      ]
      #v(6pt)
      #align(center)[
        #box(inset: (x: 16pt, y: 6pt), radius: 20pt, fill: success)[
          #text(size: 11pt, weight: "bold", fill: white)[+90% продуктивности]
        ]
      ]
    ],
  )
]

// ============================================================
// SLIDE 3: What is KommoMCP
// ============================================================
#slide(title: "Что такое KommoMCP", subtitle: "AI-ассистент в Telegram для вашей CRM", bar-color: primary)[
  #grid(
    columns: (1fr, 1fr, 1fr, 1fr),
    gutter: 8pt,
    feature-card("🤖", "Telegram-бот", "Пишите как коллеге — понимает естественный язык", bg: blue-light),
    feature-card("📊", "Аналитика", "Конверсии, прогнозы, здоровье воронки по запросу", bg: green-light),
    feature-card("⚡", "Автоматизация", "Массовые операции, распределение, шаблоны", bg: orange-light),
    feature-card("🧠", "AI-коучинг", "Подсказки по закрытию, квалификация, риски", bg: purple-light),
  )
  #v(6pt)
  #grid(
    columns: (1fr, 1fr, 1fr, 1fr),
    gutter: 8pt,
    feature-card("🏢", "Мульти-CRM", "Несколько CRM-аккаунтов, переключение", bg: purple-light),
    feature-card("🔒", "Безопасность", "Изоляция данных, подтверждение опасных операций", bg: pink-light),
    feature-card("📱", "Везде", "Телефон, планшет, компьютер — CRM под рукой", bg: blue-light),
    feature-card("🔌", "Интеграции", "MCP: Claude, Cursor, Windsurf, n8n", bg: green-light),
  )
  #v(8pt)
  // Bottom infographic strip
  #align(center)[
    #box(inset: (x: 20pt, y: 8pt), radius: 20pt, fill: primary)[
      #text(size: 11pt, fill: white)[
        #badge("54", bg: accent) инструмента  ·  #badge("258", bg: success) действий  ·  #badge("10", bg: rgb("#7c4dff")) шаблонов  ·  #badge("24/7", bg: primary.lighten(30%)) доступность
      ]
    ]
  ]
]

// ============================================================
// SLIDE 4: Key metrics with infographics
// ============================================================
#slide(title: "Ключевые метрики", subtitle: "Цифры, которые говорят сами за себя", bar-color: success)[
  #grid(
    columns: (1fr, 1fr, 1fr, 1fr),
    gutter: 10pt,
    metric("54", "инструмента CRM", icon: "🔧", color: primary),
    metric("258", "действий", icon: "⚡", color: accent),
    metric("\<2ms", "планирование", icon: "🎯", color: success),
    metric("\$0", "за планирование", icon: "💰", color: rgb("#7c4dff")),
  )
  #v(8pt)
  #grid(
    columns: (1fr, 1fr, 1fr, 1fr),
    gutter: 10pt,
    metric("10с", "ответ на запрос", icon: "⏱️", color: rgb("#ff6f00")),
    metric("95%+", "точность", icon: "🎯", color: success),
    metric("24/7", "доступность", icon: "🌐", color: primary),
    metric("31", "автотест", icon: "✅", color: rgb("#2e7d32")),
  )
  #v(10pt)
  // Comparison infographic
  #grid(
    columns: (1fr, 20pt, 1fr),
    align: center + horizon,
    box(inset: 10pt, radius: 10pt, fill: pink-light, width: 100%)[
      #align(center)[
        #text(size: 11pt, weight: "bold", fill: accent)[❌ Без KommoMCP]\
        #v(4pt)
        #text(size: 20pt, weight: "bold", fill: accent)[20 мин]\
        #text(size: 10pt, fill: muted)[на рутинную задачу]
        #v(3pt)
        #progress-bar(100%, color: accent)
      ]
    ],
    text(size: 16pt, weight: "bold", fill: muted)[→],
    box(inset: 10pt, radius: 10pt, fill: green-light, width: 100%)[
      #align(center)[
        #text(size: 11pt, weight: "bold", fill: success)[✅ С KommoMCP]\
        #v(4pt)
        #text(size: 20pt, weight: "bold", fill: success)[2 мин]\
        #text(size: 10pt, fill: muted)[та же задача]
        #v(3pt)
        #progress-bar(10%, color: success)
      ]
    ],
  )
]

// ============================================================
// SLIDE 5: How it works — pipeline infographic
// ============================================================
#slide(title: "Как это работает", subtitle: "От вопроса до результата за секунды", bar-color: rgb("#7c4dff"))[
  #v(2pt)
  // Main pipeline
  #align(center)[
    #box(inset: 12pt, radius: 12pt, fill: light-bg, width: 100%)[
      #grid(
        columns: (1fr, 24pt, 1fr, 24pt, 1fr, 24pt, 1fr),
        align: center + horizon,
        box(inset: 8pt, radius: 8pt, fill: blue-light, stroke: 1pt + rgb("#90caf9"))[
          #text(size: 12pt)[💬]\
          #text(size: 10pt, weight: "bold")[Запрос]\
          #text(size: 8pt, fill: muted)[Telegram]
        ],
        text(size: 14pt, fill: accent, weight: "bold")[▸],
        box(inset: 8pt, radius: 8pt, fill: purple-light, stroke: 1pt + rgb("#b39ddb"))[
          #text(size: 12pt)[🎯]\
          #text(size: 10pt, weight: "bold")[Планировщик]\
          #text(size: 8pt, fill: muted)[\<2ms]
        ],
        text(size: 14pt, fill: accent, weight: "bold")[▸],
        box(inset: 8pt, radius: 8pt, fill: orange-light, stroke: 1pt + rgb("#ffcc80"))[
          #text(size: 12pt)[🤖]\
          #text(size: 10pt, weight: "bold")[AI (GPT-4o)]\
          #text(size: 8pt, fill: muted)[2-6 tools]
        ],
        text(size: 14pt, fill: accent, weight: "bold")[▸],
        box(inset: 8pt, radius: 8pt, fill: green-light, stroke: 1pt + rgb("#a5d6a7"))[
          #text(size: 12pt)[📊]\
          #text(size: 10pt, weight: "bold")[Результат]\
          #text(size: 8pt, fill: muted)[Ваши данные]
        ],
      )
    ]
  ]

  #v(8pt)
  #text(size: 12pt, weight: "bold")[📋 Пример: «Проведи аналитику по всем воронкам»]
  #v(4pt)

  // Step-by-step with numbered circles
  #grid(
    columns: (1fr, 1fr, 1fr, 1fr),
    gutter: 8pt,
    box(inset: 8pt, radius: 8pt, fill: white, stroke: 1.5pt + primary)[
      #box(inset: 4pt, radius: 12pt, fill: primary)[
        #text(size: 9pt, weight: "bold", fill: white)[1]
      ]
      #text(size: 10pt, weight: "bold")[ Интент]\
      #text(size: 9pt, fill: muted)[Определяет: _аналитика_\
      Скоринг ключевых слов]
    ],
    box(inset: 8pt, radius: 8pt, fill: white, stroke: 1.5pt + rgb("#7c4dff"))[
      #box(inset: 4pt, radius: 12pt, fill: rgb("#7c4dff"))[
        #text(size: 9pt, weight: "bold", fill: white)[2]
      ]
      #text(size: 10pt, weight: "bold")[ Граф]\
      #text(size: 9pt, fill: muted)[Выбирает 4 из 54\
      инструментов по графу]
    ],
    box(inset: 8pt, radius: 8pt, fill: white, stroke: 1.5pt + accent)[
      #box(inset: 4pt, radius: 12pt, fill: accent)[
        #text(size: 9pt, weight: "bold", fill: white)[3]
      ]
      #text(size: 10pt, weight: "bold")[ API]\
      #text(size: 9pt, fill: muted)[Запрашивает данные\
      из Kommo по цепочке]
    ],
    box(inset: 8pt, radius: 8pt, fill: white, stroke: 1.5pt + success)[
      #box(inset: 4pt, radius: 12pt, fill: success)[
        #text(size: 9pt, weight: "bold", fill: white)[4]
      ]
      #text(size: 10pt, weight: "bold")[ Ответ]\
      #text(size: 9pt, fill: muted)[AI формирует отчёт\
      с выводами]
    ],
  )

  #v(6pt)
  // Tool filtering infographic
  #align(center)[
    #box(inset: 8pt, radius: 8pt, fill: purple-light, width: 80%)[
      #grid(
        columns: (1fr, 30pt, 1fr),
        align: center + horizon,
        [
          #text(size: 10pt, fill: muted)[Все инструменты]\
          #text(size: 16pt, weight: "bold")[54]
          #progress-bar(100%, color: rgb("#bdbdbd"))
        ],
        text(size: 14pt, weight: "bold", fill: accent)[→],
        [
          #text(size: 10pt, fill: muted)[После планировщика]\
          #text(size: 16pt, weight: "bold", fill: success)[2-6]
          #progress-bar(8%, color: success)
        ],
      )
    ]
  ]
]

// ============================================================
// SLIDE 6: Use cases
// ============================================================
#slide(title: "Сценарии использования", subtitle: "Что умеет бот — примеры реальных запросов", bar-color: rgb("#ff6f00"))[
  #grid(
    columns: (1fr, 1fr),
    gutter: 12pt,
    [
      #box(inset: 8pt, radius: 8pt, fill: blue-light, width: 100%)[
        #text(size: 11pt, weight: "bold", fill: primary)[📊 Для руководителя]
        #v(3pt)
        #text(size: 10pt)[
          💬 _«Конверсия по воронкам за месяц»_\
          💬 _«Кто закрыл больше всех?»_\
          💬 _«Прогноз выручки на квартал»_\
          💬 _«Сделки в зоне риска?»_
        ]
      ]
      #v(4pt)
      #box(inset: 8pt, radius: 8pt, fill: orange-light, width: 100%)[
        #text(size: 11pt, weight: "bold", fill: rgb("#e65100"))[⚙️ Для администратора]
        #v(3pt)
        #text(size: 10pt)[
          💬 _«Настрой воронку для B2B»_\
          💬 _«Создай 50 тестовых сделок»_\
          💬 _«Распредели лиды»_\
          💬 _«Очисти дубликаты»_
        ]
      ]
    ],
    [
      #box(inset: 8pt, radius: 8pt, fill: green-light, width: 100%)[
        #text(size: 11pt, weight: "bold", fill: rgb("#2e7d32"))[💼 Для менеджера]
        #v(3pt)
        #text(size: 10pt)[
          💬 _«Перемести сделку в Переговоры»_\
          💬 _«Добавь заметку к сделке»_\
          💬 _«Квалифицируй лид по BANT»_\
          💬 _«Как закрыть эту сделку?»_
        ]
      ]
      #v(4pt)
      #box(inset: 8pt, radius: 8pt, fill: purple-light, width: 100%)[
        #text(size: 11pt, weight: "bold", fill: rgb("#4a148c"))[🔄 Автоматизация]
        #v(3pt)
        #text(size: 10pt)[
          💬 _«Спящие клиенты за 90 дней»_\
          💬 _«Массово перемести без задач»_\
          💬 _«Просроченные задачи?»_\
          💬 _«Реактивируй потерянных»_
        ]
      ]
    ],
  )
  #v(6pt)
  // Category stats strip
  #align(center)[
    #box(inset: (x: 12pt, y: 6pt), radius: 16pt, fill: light-bg, stroke: 0.5pt + rgb("#dee2e6"))[
      #text(size: 9pt, fill: muted)[
        #badge("12", bg: primary) аналитика  ·  #badge("8", bg: accent) сделки  ·  #badge("10", bg: success) автоматизация  ·  #badge("6", bg: rgb("#7c4dff")) настройка  ·  #badge("8", bg: rgb("#ff6f00")) коучинг  ·  #badge("10", bg: rgb("#2e7d32")) контакты
      ]
    ]
  ]
]

// ============================================================
// SLIDE 7: Architecture (simplified)
// ============================================================
#slide(title: "Архитектура", subtitle: "Умный планировщик + AI = точные результаты", bar-color: primary)[
  #align(center)[
    #box(inset: 12pt, radius: 12pt, fill: light-bg, width: 100%)[
      #grid(
        columns: (1fr, 24pt, 1fr, 24pt, 1fr),
        align: center + horizon,
        [
          #box(inset: 10pt, radius: 10pt, fill: purple-light, width: 100%, stroke: 1pt + rgb("#b39ddb"))[
            #text(size: 12pt, weight: "bold")[🎯 Планировщик]\
            #v(2pt)
            #text(size: 9pt, fill: muted)[
              Граф 54 инструментов\
              Backward chaining\
              Topo sort + параллелизм
            ]
            #v(3pt)
            #badge("\<2ms", bg: success) #badge("\$0", bg: rgb("#7c4dff"))
          ]
        ],
        text(size: 16pt, fill: accent, weight: "bold")[▸],
        [
          #box(inset: 10pt, radius: 10pt, fill: orange-light, width: 100%, stroke: 1pt + rgb("#ffcc80"))[
            #text(size: 12pt, weight: "bold")[🤖 AI-исполнитель]\
            #v(2pt)
            #text(size: 9pt, fill: muted)[
              Только нужные tools\
              Порядок из плана\
              Передача параметров
            ]
            #v(3pt)
            #badge("GPT-4o", bg: primary) #badge("RAG", bg: accent)
          ]
        ],
        text(size: 16pt, fill: accent, weight: "bold")[▸],
        [
          #box(inset: 10pt, radius: 10pt, fill: green-light, width: 100%, stroke: 1pt + rgb("#a5d6a7"))[
            #text(size: 12pt, weight: "bold")[📡 Kommo API]\
            #v(2pt)
            #text(size: 9pt, fill: muted)[
              Сделки, контакты\
              Воронки, аналитика\
              Задачи, заметки
            ]
            #v(3pt)
            #badge("REST", bg: rgb("#2e7d32")) #badge("OAuth", bg: rgb("#ff6f00"))
          ]
        ],
      )
    ]
  ]

  #v(6pt)
  // Before/After comparison
  #grid(
    columns: (1fr, 1fr, 1fr),
    gutter: 10pt,
    box(inset: 10pt, radius: 8pt, fill: pink-light, stroke: 1pt + accent.lighten(50%))[
      #align(center)[
        #text(size: 11pt, weight: "bold", fill: accent)[❌ Без планировщика]\
        #v(3pt)
        #text(size: 20pt, weight: "bold")[54]
        #text(size: 9pt, fill: muted)[ инструмента]\
        #text(size: 10pt)[AI гадает что вызвать]
        #v(2pt)
        #progress-bar(100%, color: accent)
        #text(size: 9pt, fill: accent)[~80% точность]
      ]
    ],
    box(inset: 10pt, radius: 8pt, fill: green-light, stroke: 1pt + success.lighten(50%))[
      #align(center)[
        #text(size: 11pt, weight: "bold", fill: success)[✅ С планировщиком]\
        #v(3pt)
        #text(size: 20pt, weight: "bold")[2-6]
        #text(size: 9pt, fill: muted)[ инструментов]\
        #text(size: 10pt)[Точный план + порядок]
        #v(2pt)
        #progress-bar(95%, color: success)
        #text(size: 9pt, fill: success)[95%+ точность]
      ]
    ],
    box(inset: 10pt, radius: 8pt, fill: blue-light, stroke: 1pt + primary.lighten(50%))[
      #align(center)[
        #text(size: 11pt, weight: "bold", fill: primary)[🔗 Зависимости]\
        #v(3pt)
        #text(size: 20pt, weight: "bold")[24]
        #text(size: 9pt, fill: muted)[ связи в графе]\
        #text(size: 10pt)[Авто-разрешение deps]
        #v(2pt)
        #progress-bar(100%, color: primary)
        #text(size: 9pt, fill: primary)[0 пропущенных шагов]
      ]
    ],
  )
]

// ============================================================
// SLIDE 8: Multi-tenant SaaS
// ============================================================
#slide(title: "SaaS-модель", subtitle: "Один бот — множество компаний", bar-color: rgb("#7c4dff"))[
  #grid(
    columns: (1fr, 1fr),
    gutter: 16pt,
    [
      #text(size: 12pt, weight: "bold")[🏢 Мульти-тенант архитектура]
      #v(4pt)
      // Tenant diagram
      #box(inset: 10pt, radius: 8pt, fill: light-bg, width: 100%)[
        #align(center)[
          #box(inset: 6pt, radius: 6pt, fill: primary)[
            #text(size: 10pt, fill: white, weight: "bold")[🤖 KommoMCP Bot]
          ]
          #v(4pt)
          #grid(
            columns: (1fr, 1fr, 1fr),
            gutter: 4pt,
            box(inset: 4pt, radius: 4pt, fill: blue-light)[
              #align(center)[
                #text(size: 8pt, weight: "bold")[Компания A]\
                #text(size: 7pt, fill: muted)[своя БД + API]
              ]
            ],
            box(inset: 4pt, radius: 4pt, fill: green-light)[
              #align(center)[
                #text(size: 8pt, weight: "bold")[Компания B]\
                #text(size: 7pt, fill: muted)[своя БД + API]
              ]
            ],
            box(inset: 4pt, radius: 4pt, fill: orange-light)[
              #align(center)[
                #text(size: 8pt, weight: "bold")[Компания C]\
                #text(size: 7pt, fill: muted)[своя БД + API]
              ]
            ],
          )
        ]
      ]
      #v(4pt)
      #text(size: 10pt)[
        ✅ *Изоляция данных* — каждый тенант в своей БД\
        ✅ *Несколько CRM* — один юзер, много аккаунтов\
        ✅ *Свои API-ключи* — безопасное хранение\
        ✅ *Быстрое подключение* — /connect и готово\
        ✅ *Переключение* — /switch между CRM
      ]
    ],
    [
      #text(size: 12pt, weight: "bold")[💳 Модель монетизации]
      #v(4pt)

      #box(inset: 10pt, radius: 8pt, fill: green-light, width: 100%, stroke: 1pt + success.lighten(50%))[
        #grid(columns: (auto, 1fr), gutter: 8pt, align: horizon,
          box(inset: 6pt, radius: 16pt, fill: success)[
            #text(size: 10pt, fill: white, weight: "bold")[F]
          ],
          [
            #text(size: 11pt, weight: "bold", fill: success)[Freemium]\
            #text(size: 9pt, fill: muted)[Базовые запросы бесплатно, аналитика — подписка]
          ],
        )
      ]
      #v(4pt)
      #box(inset: 10pt, radius: 8pt, fill: blue-light, width: 100%, stroke: 1pt + primary.lighten(50%))[
        #grid(columns: (auto, 1fr), gutter: 8pt, align: horizon,
          box(inset: 6pt, radius: 16pt, fill: primary)[
            #text(size: 10pt, fill: white, weight: "bold")[P]
          ],
          [
            #text(size: 11pt, weight: "bold", fill: primary)[Per-seat]\
            #text(size: 9pt, fill: muted)[Оплата за пользователя, масштабируется]
          ],
        )
      ]
      #v(4pt)
      #box(inset: 10pt, radius: 8pt, fill: orange-light, width: 100%, stroke: 1pt + rgb("#ff6f00").lighten(50%))[
        #grid(columns: (auto, 1fr), gutter: 8pt, align: horizon,
          box(inset: 6pt, radius: 16pt, fill: rgb("#e65100"))[
            #text(size: 10pt, fill: white, weight: "bold")[E]
          ],
          [
            #text(size: 11pt, weight: "bold", fill: rgb("#e65100"))[Enterprise]\
            #text(size: 9pt, fill: muted)[On-premise, кастомные интеграции]
          ],
        )
      ]
      #v(6pt)
      #align(center)[
        #box(inset: (x: 12pt, y: 5pt), radius: 16pt, fill: rgb("#7c4dff").lighten(85%))[
          #text(size: 9pt, fill: rgb("#4a148c"))[💡 Средний чек: *от 2 000 ₽/мес* за пользователя]
        ]
      ]
    ],
  )
]

// ============================================================
// SLIDE 9: Competitive advantage
// ============================================================
#slide(title: "Конкурентные преимущества", subtitle: "Почему KommoMCP — это следующий уровень", bar-color: success)[
  #table(
    columns: (2fr, 1fr, 1fr, 1fr),
    inset: 7pt,
    stroke: 0.5pt + rgb("#dee2e6"),
    fill: (_, row) => if row == 0 { primary } else if calc.odd(row) { light-bg } else { white },

    text(fill: white, weight: "bold", size: 10pt)[Возможность],
    text(fill: white, weight: "bold", size: 10pt)[KommoMCP],
    text(fill: white, weight: "bold", size: 10pt)[Обычные боты],
    text(fill: white, weight: "bold", size: 10pt)[Ручная работа],

    text(size: 10pt)[Аналитика по запросу], text(fill: success, size: 10pt)[✅ 10 сек], text(size: 10pt)[⚠️ шаблоны], text(size: 10pt)[❌ 30+ мин],
    text(size: 10pt)[Понимание контекста], text(fill: success, size: 10pt)[✅ AI], text(size: 10pt)[❌ кнопки], text(size: 10pt)[—],
    text(size: 10pt)[Цепочки действий], text(fill: success, size: 10pt)[✅ авто], text(size: 10pt)[❌ по одному], text(size: 10pt)[❌ вручную],
    text(size: 10pt)[Прогнозы и AI-коучинг], text(fill: success, size: 10pt)[✅ встроено], text(size: 10pt)[❌ нет], text(size: 10pt)[❌ нет],
    text(size: 10pt)[Мульти-CRM], text(fill: success, size: 10pt)[✅ да], text(size: 10pt)[❌ нет], text(size: 10pt)[⚠️ вкладки],
    text(size: 10pt)[Работа с телефона], text(fill: success, size: 10pt)[✅ Telegram], text(size: 10pt)[⚠️ веб], text(size: 10pt)[⚠️ приложение],
    text(size: 10pt)[Обучение], text(fill: success, size: 10pt)[✅ 0 минут], text(size: 10pt)[⚠️ 1 час], text(size: 10pt)[❌ 1-2 недели],
    text(size: 10pt)[Масштабирование], text(fill: success, size: 10pt)[✅ SaaS], text(size: 10pt)[⚠️ лимиты], text(size: 10pt)[❌ линейно],
  )
  #v(4pt)
  #align(center)[
    #box(inset: (x: 16pt, y: 6pt), radius: 16pt, fill: green-light, stroke: 1pt + success.lighten(50%))[
      #text(size: 10pt, fill: rgb("#2e7d32"))[
        *8 из 8* преимуществ ✅  ·  Ближайший конкурент: *2 из 8*
      ]
    ]
  ]
]

// ============================================================
// SLIDE 10: Roadmap — timeline style
// ============================================================
#slide(title: "Дорожная карта", subtitle: "Что уже есть и что впереди", bar-color: rgb("#ff6f00"))[
  #grid(
    columns: (1fr, 1fr, 1fr),
    gutter: 10pt,
    // Column 1: Done
    box(inset: 10pt, radius: 10pt, fill: green-light, stroke: 1pt + success.lighten(50%), width: 100%)[
      #align(center)[
        #box(inset: 5pt, radius: 14pt, fill: success)[
          #text(size: 10pt, fill: white, weight: "bold")[✅]
        ]
      ]
      #v(2pt)
      #align(center)[#text(size: 11pt, weight: "bold", fill: success)[Реализовано]]
      #v(4pt)
      #text(size: 9pt)[
        ✅ 54 инструмента CRM\
        ✅ AI-планировщик (\<2ms)\
        ✅ Мульти-тенант SaaS\
        ✅ RAG-промпты\
        ✅ Админ-панель (React)\
        ✅ Big Data (PostgreSQL)\
        ✅ 10 шаблонов воронок\
        ✅ AI-коучинг и скоринг\
        ✅ MCP-протокол\
        ✅ Мульти-CRM
      ]
      #v(3pt)
      #progress-bar(100%, color: success)
    ],
    // Column 2: In progress
    box(inset: 10pt, radius: 10pt, fill: blue-light, stroke: 1pt + primary.lighten(50%), width: 100%)[
      #align(center)[
        #box(inset: 5pt, radius: 14pt, fill: primary)[
          #text(size: 10pt, fill: white, weight: "bold")[🚀]
        ]
      ]
      #v(2pt)
      #align(center)[#text(size: 11pt, weight: "bold", fill: primary)[В разработке]]
      #v(4pt)
      #text(size: 9pt)[
        🔄 Replanning при ошибках\
        🔍 Верификация (AI)\
        📈 Обучение на цепочках\
        🤝 A2A-протокол\
        💳 Биллинг и подписки\
        📱 Telegram Mini App\
        🌍 Мультиязычность\
        🔗 WhatsApp
      ]
      #v(3pt)
      #progress-bar(30%, color: primary)
    ],
    // Column 3: Goal
    box(inset: 10pt, radius: 10pt, fill: orange-light, stroke: 1pt + rgb("#ff6f00").lighten(50%), width: 100%)[
      #align(center)[
        #box(inset: 5pt, radius: 14pt, fill: rgb("#e65100"))[
          #text(size: 10pt, fill: white, weight: "bold")[🎯]
        ]
      ]
      #v(2pt)
      #align(center)[#text(size: 11pt, weight: "bold", fill: rgb("#e65100"))[Цель 2026]]
      #v(4pt)
      #text(size: 9pt)[
        🏆 \#1 AI-ассистент для\
        #h(12pt) CRM в СНГ\
        \
        📊 1 000+ пользователей\
        \
        🤖 100+ инструментов\
        \
        🌐 3+ CRM-системы\
        #h(12pt) (Kommo, Bitrix, AMO)\
        \
        💰 MRR \> 500K ₽
      ]
      #v(3pt)
      #progress-bar(10%, color: rgb("#e65100"))
    ],
  )
]

// ============================================================
// SLIDE 11: CTA
// ============================================================
#set page(fill: dark-bg)
#place(top + left, dx: -20mm, dy: -16mm,
  rect(width: 294mm, height: 4pt, fill: accent)
)
#place(top + right, dx: -15mm, dy: 25mm,
  circle(radius: 30pt, fill: rgb("#1a1a3e"))
)
#place(bottom + left, dx: 15mm, dy: -25mm,
  circle(radius: 24pt, fill: accent.lighten(80%))
)
#v(16mm)
#align(center)[
  #box(inset: 10pt, radius: 24pt, fill: accent)[
    #text(size: 18pt, weight: "bold", fill: white)[K]
  ]
  #v(8pt)
  #text(size: 32pt, weight: "bold", fill: white)[Готовы попробовать?]
  #v(6pt)
  #text(size: 14pt, fill: rgb("#a0a0c0"))[
    Подключите вашу CRM за 2 минуты
  ]
  #v(16pt)

  #box(inset: (x: 28pt, y: 10pt), radius: 24pt, fill: accent)[
    #text(size: 16pt, weight: "bold", fill: white)[\@kommo_wizard_bot]
  ]

  #v(16pt)
  #line(length: 50pt, stroke: 1pt + rgb("#444466"))
  #v(12pt)

  #grid(
    columns: (1fr, 1fr, 1fr),
    gutter: 20pt,
    [
      #box(inset: 6pt, radius: 14pt, fill: rgb("#1a1a3e"))[
        #text(size: 11pt, weight: "bold", fill: accent)[1]
      ]
      #v(4pt)
      #text(size: 12pt, weight: "bold", fill: white)[/start]\
      #text(size: 10pt, fill: rgb("#8888aa"))[Запустите бота]
    ],
    [
      #box(inset: 6pt, radius: 14pt, fill: rgb("#1a1a3e"))[
        #text(size: 11pt, weight: "bold", fill: accent)[2]
      ]
      #v(4pt)
      #text(size: 12pt, weight: "bold", fill: white)[/connect]\
      #text(size: 10pt, fill: rgb("#8888aa"))[Подключите CRM]
    ],
    [
      #box(inset: 6pt, radius: 14pt, fill: rgb("#1a1a3e"))[
        #text(size: 11pt, weight: "bold", fill: accent)[3]
      ]
      #v(4pt)
      #text(size: 12pt, weight: "bold", fill: white)[Спросите]\
      #text(size: 10pt, fill: rgb("#8888aa"))[Любой вопрос по CRM]
    ],
  )

  #v(16pt)
  #text(size: 10pt, fill: rgb("#666688"))[
    KommoMCP — Open Source · github.com/ampulex-23/KommoMCP
  ]
]
