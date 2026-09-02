"""Translations for the graphical interface.

English is the default and the fallback: a missing key in another language
falls back to the English string, and a missing key everywhere returns the key
itself, so the interface degrades gracefully instead of crashing.

The chosen language is stored next to the user's home directory so that the
application starts in the same language next time.
"""

from __future__ import annotations

import json
import locale
import os

__all__ = ["LANGUAGES", "DEFAULT_LANGUAGE", "translate", "set_language",
           "get_language", "detect_language", "load_preference",
           "save_preference", "available_languages"]

DEFAULT_LANGUAGE = "en"

LANGUAGES = {"en": "English", "uk": "Українська", "ru": "Русский"}

_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".stegolab.json")

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # -- window and tabs ------------------------------------------------
        "app.title": "stegolab - adaptive image steganography",
        "tab.embed": "Embed",
        "tab.extract": "Extract",
        "tab.analyze": "Analyse",
        "tab.benchmark": "Benchmark",
        "tab.about": "About",

        # -- shared ---------------------------------------------------------
        "common.browse": "Browse...",
        "common.save_as": "Save as...",
        "common.image": "Image",
        "common.cover": "Cover image",
        "common.stego": "Stego image",
        "common.output": "Output file",
        "common.method": "Method",
        "common.key": "Position key",
        "common.password": "Password",
        "common.bits": "Bits per sample",
        "common.map": "Complexity map",
        "common.band_bits": "Map quantisation (bits)",
        "common.ecc": "Error correction (parity bytes)",
        "common.compress": "Compress with zlib",
        "common.grayscale": "Grayscale",
        "common.channels": "Channels",
        "common.channels_all": "all",
        "common.options": "Options",
        "common.result": "Result",
        "common.ready": "Ready",
        "common.working": "Working...",
        "common.error": "Error",
        "common.language": "Language",
        "common.copy": "Copy",
        "common.clear": "Clear",
        "common.run": "Run",
        "common.cancel": "Cancel",
        "common.close": "Close",
        "common.none": "none",
        "common.yes": "yes",
        "common.no": "no",

        # -- embed tab ------------------------------------------------------
        "embed.title": "Hide a message inside an image",
        "embed.message": "Message",
        "embed.from_text": "Type the text",
        "embed.from_file": "Read from file",
        "embed.message_file": "Message file",
        "embed.button": "Embed message",
        "embed.done": "Message embedded",
        "embed.saved_to": "Saved to",
        "embed.capacity": "Capacity",
        "embed.capacity_hint": "Maximum message size for this image and method",
        "embed.no_cover": "Choose a cover image first",
        "embed.no_message": "The message is empty",
        "embed.no_output": "Choose where to save the result",
        "embed.preview_cover": "Cover",
        "embed.preview_changes": "Changed samples",
        "embed.preview_hint": "White marks the pixels that were modified",

        # -- extract tab ----------------------------------------------------
        "extract.title": "Recover a message from an image",
        "extract.button": "Extract message",
        "extract.done": "Message recovered",
        "extract.empty": "Nothing was recovered",
        "extract.save": "Save message to file",
        "extract.no_image": "Choose a stego image first",
        "extract.hint": "The method, key and parameters must match the ones "
                        "used for embedding",
        "extract.binary": "The message is not text; save it to a file",

        # -- analyse tab ----------------------------------------------------
        "analyze.title": "Steganalysis and image quality",
        "analyze.button": "Analyse",
        "analyze.compare": "Compare with a cover image (optional)",
        "analyze.detect": "Detection",
        "analyze.quality": "Quality",
        "analyze.capacity_table": "Capacity by method",
        "analyze.chi2": "Chi-square probability",
        "analyze.spa": "SPA estimate",
        "analyze.ones": "Ones in the lowest bit plane",
        "analyze.autocorr": "Lag-1 autocorrelation",
        "analyze.verdict_clean": "No sign of LSB replacement",
        "analyze.verdict_suspect": "Traces of LSB replacement detected",
        "analyze.verdict_hint": "These are classical detectors: they see LSB "
                                "replacement but not LSB matching",

        # -- benchmark tab --------------------------------------------------
        "bench.title": "Compare methods on synthetic or real images",
        "bench.images": "Images",
        "bench.synthetic": "Synthetic covers",
        "bench.folder": "Image folder",
        "bench.count": "Number of images",
        "bench.size": "Size of synthetic covers",
        "bench.payloads": "Payloads (bits per pixel)",
        "bench.methods": "Methods",
        "bench.run": "Run benchmark",
        "bench.stop": "Stop",
        "bench.export": "Export CSV",
        "bench.progress": "Progress",
        "bench.col_method": "Method",
        "bench.col_bpp": "bpp",
        "bench.col_psnr": "PSNR, dB",
        "bench.col_ssim": "SSIM",
        "bench.col_spa": "SPA",
        "bench.col_time": "Embed, ms",
        "bench.col_recovered": "Recovered",
        "bench.done": "Benchmark finished",
        "bench.cancelled": "Benchmark cancelled",
        "bench.hint": "Lower SPA means the message is harder to detect at the "
                      "same payload",

        # -- about tab ------------------------------------------------------
        "about.title": "About stegolab",
        "about.description": "A research bench for image steganography and "
                             "steganalysis: content-adaptive LSB embedding, "
                             "baseline methods, quality metrics, container "
                             "attacks and classical detectors.",
        "about.selftest": "Run determinism self-test",
        "about.selftest_hint": "Run this on two machines and compare the "
                               "digest: identical digests mean the two "
                               "installations can exchange stego images",
        "about.environment": "Environment",
        "about.docs": "Documentation and source code",
        "about.warning_title": "What this tool does not do",
        "about.warning": "The message does not survive JPEG re-encoding, "
                         "resizing or noise. Steganography hides that a "
                         "message exists; use the password option if the "
                         "content itself must stay secret.",
    },

    "uk": {
        "app.title": "stegolab - адаптивна стеганографія зображень",
        "tab.embed": "Вбудувати",
        "tab.extract": "Витягти",
        "tab.analyze": "Аналіз",
        "tab.benchmark": "Порівняння",
        "tab.about": "Про програму",

        "common.browse": "Огляд...",
        "common.save_as": "Зберегти як...",
        "common.image": "Зображення",
        "common.cover": "Зображення-контейнер",
        "common.stego": "Стего-зображення",
        "common.output": "Вихідний файл",
        "common.method": "Метод",
        "common.key": "Ключ позицій",
        "common.password": "Пароль",
        "common.bits": "Біт на відлік",
        "common.map": "Карта складності",
        "common.band_bits": "Квантування карти (біт)",
        "common.ecc": "Корекція помилок (байт надлишковості)",
        "common.compress": "Стискати zlib",
        "common.grayscale": "Відтінки сірого",
        "common.channels": "Канали",
        "common.channels_all": "усі",
        "common.options": "Параметри",
        "common.result": "Результат",
        "common.ready": "Готово",
        "common.working": "Обробка...",
        "common.error": "Помилка",
        "common.language": "Мова",
        "common.copy": "Копіювати",
        "common.clear": "Очистити",
        "common.run": "Запустити",
        "common.cancel": "Скасувати",
        "common.close": "Закрити",
        "common.none": "немає",
        "common.yes": "так",
        "common.no": "ні",

        "embed.title": "Сховати повідомлення в зображенні",
        "embed.message": "Повідомлення",
        "embed.from_text": "Ввести текст",
        "embed.from_file": "Прочитати з файлу",
        "embed.message_file": "Файл повідомлення",
        "embed.button": "Вбудувати повідомлення",
        "embed.done": "Повідомлення вбудовано",
        "embed.saved_to": "Збережено у",
        "embed.capacity": "Місткість",
        "embed.capacity_hint": "Максимальний розмір повідомлення для цього "
                               "зображення та методу",
        "embed.no_cover": "Спочатку виберіть зображення-контейнер",
        "embed.no_message": "Повідомлення порожнє",
        "embed.no_output": "Виберіть, куди зберегти результат",
        "embed.preview_cover": "Контейнер",
        "embed.preview_changes": "Змінені відліки",
        "embed.preview_hint": "Білим позначено змінені пікселі",

        "extract.title": "Відновити повідомлення із зображення",
        "extract.button": "Витягти повідомлення",
        "extract.done": "Повідомлення відновлено",
        "extract.empty": "Нічого не відновлено",
        "extract.save": "Зберегти повідомлення у файл",
        "extract.no_image": "Спочатку виберіть стего-зображення",
        "extract.hint": "Метод, ключ і параметри мають збігатися з тими, що "
                        "використовувалися під час вбудовування",
        "extract.binary": "Повідомлення не є текстом, збережіть його у файл",

        "analyze.title": "Стегоаналіз та якість зображення",
        "analyze.button": "Аналізувати",
        "analyze.compare": "Порівняти з контейнером (необов'язково)",
        "analyze.detect": "Виявлення",
        "analyze.quality": "Якість",
        "analyze.capacity_table": "Місткість за методами",
        "analyze.chi2": "Ймовірність за хі-квадрат",
        "analyze.spa": "Оцінка SPA",
        "analyze.ones": "Одиниці в молодшому біт-плані",
        "analyze.autocorr": "Автокореляція лагу 1",
        "analyze.verdict_clean": "Ознак заміни молодших бітів не виявлено",
        "analyze.verdict_suspect": "Виявлено сліди заміни молодших бітів",
        "analyze.verdict_hint": "Це класичні детектори: вони бачать заміну "
                                "молодшого біта, але не LSB matching",

        "bench.title": "Порівняння методів на синтетичних або реальних зображеннях",
        "bench.images": "Зображення",
        "bench.synthetic": "Синтетичні контейнери",
        "bench.folder": "Тека із зображеннями",
        "bench.count": "Кількість зображень",
        "bench.size": "Розмір синтетичних контейнерів",
        "bench.payloads": "Навантаження (біт на піксель)",
        "bench.methods": "Методи",
        "bench.run": "Запустити порівняння",
        "bench.stop": "Зупинити",
        "bench.export": "Експорт CSV",
        "bench.progress": "Прогрес",
        "bench.col_method": "Метод",
        "bench.col_bpp": "біт/піксель",
        "bench.col_psnr": "PSNR, дБ",
        "bench.col_ssim": "SSIM",
        "bench.col_spa": "SPA",
        "bench.col_time": "Вбудовування, мс",
        "bench.col_recovered": "Відновлено",
        "bench.done": "Порівняння завершено",
        "bench.cancelled": "Порівняння скасовано",
        "bench.hint": "Менше значення SPA означає, що повідомлення важче "
                      "виявити за того самого навантаження",

        "about.title": "Про stegolab",
        "about.description": "Дослідницький стенд зі стеганографії та "
                             "стегоаналізу зображень: контентно-адаптивне "
                             "вбудовування в молодші біти, базові методи, "
                             "метрики якості, атаки на контейнер і класичні "
                             "детектори.",
        "about.selftest": "Перевірка детермінізму",
        "about.selftest_hint": "Запустіть на двох машинах і порівняйте "
                               "відбиток: однакові відбитки означають, що "
                               "обидві збірки сумісні між собою",
        "about.environment": "Середовище",
        "about.docs": "Документація та вихідний код",
        "about.warning_title": "Чого програма не робить",
        "about.warning": "Повідомлення не переживає перезбереження в JPEG, "
                         "масштабування чи шум. Стеганографія приховує сам "
                         "факт передавання; якщо потрібно захистити зміст, "
                         "використовуйте пароль.",
    },

    "ru": {
        "app.title": "stegolab - адаптивная стеганография изображений",
        "tab.embed": "Встроить",
        "tab.extract": "Извлечь",
        "tab.analyze": "Анализ",
        "tab.benchmark": "Сравнение",
        "tab.about": "О программе",

        "common.browse": "Обзор...",
        "common.save_as": "Сохранить как...",
        "common.image": "Изображение",
        "common.cover": "Изображение-контейнер",
        "common.stego": "Стего-изображение",
        "common.output": "Выходной файл",
        "common.method": "Метод",
        "common.key": "Ключ позиций",
        "common.password": "Пароль",
        "common.bits": "Бит на отсчёт",
        "common.map": "Карта сложности",
        "common.band_bits": "Квантование карты (бит)",
        "common.ecc": "Коррекция ошибок (байт избыточности)",
        "common.compress": "Сжимать zlib",
        "common.grayscale": "Градации серого",
        "common.channels": "Каналы",
        "common.channels_all": "все",
        "common.options": "Параметры",
        "common.result": "Результат",
        "common.ready": "Готово",
        "common.working": "Обработка...",
        "common.error": "Ошибка",
        "common.language": "Язык",
        "common.copy": "Копировать",
        "common.clear": "Очистить",
        "common.run": "Запустить",
        "common.cancel": "Отмена",
        "common.close": "Закрыть",
        "common.none": "нет",
        "common.yes": "да",
        "common.no": "нет",

        "embed.title": "Спрятать сообщение в изображении",
        "embed.message": "Сообщение",
        "embed.from_text": "Ввести текст",
        "embed.from_file": "Прочитать из файла",
        "embed.message_file": "Файл сообщения",
        "embed.button": "Встроить сообщение",
        "embed.done": "Сообщение встроено",
        "embed.saved_to": "Сохранено в",
        "embed.capacity": "Ёмкость",
        "embed.capacity_hint": "Максимальный размер сообщения для этого "
                               "изображения и метода",
        "embed.no_cover": "Сначала выберите изображение-контейнер",
        "embed.no_message": "Сообщение пустое",
        "embed.no_output": "Выберите, куда сохранить результат",
        "embed.preview_cover": "Контейнер",
        "embed.preview_changes": "Изменённые отсчёты",
        "embed.preview_hint": "Белым отмечены изменённые пиксели",

        "extract.title": "Восстановить сообщение из изображения",
        "extract.button": "Извлечь сообщение",
        "extract.done": "Сообщение восстановлено",
        "extract.empty": "Ничего не восстановлено",
        "extract.save": "Сохранить сообщение в файл",
        "extract.no_image": "Сначала выберите стего-изображение",
        "extract.hint": "Метод, ключ и параметры должны совпадать с теми, "
                        "что использовались при встраивании",
        "extract.binary": "Сообщение не является текстом, сохраните его в файл",

        "analyze.title": "Стегоанализ и качество изображения",
        "analyze.button": "Анализировать",
        "analyze.compare": "Сравнить с контейнером (необязательно)",
        "analyze.detect": "Обнаружение",
        "analyze.quality": "Качество",
        "analyze.capacity_table": "Ёмкость по методам",
        "analyze.chi2": "Вероятность по хи-квадрат",
        "analyze.spa": "Оценка SPA",
        "analyze.ones": "Единицы в младшем бит-плане",
        "analyze.autocorr": "Автокорреляция лага 1",
        "analyze.verdict_clean": "Признаков замены младших бит не найдено",
        "analyze.verdict_suspect": "Обнаружены следы замены младших бит",
        "analyze.verdict_hint": "Это классические детекторы: они видят замену "
                                "младшего бита, но не LSB matching",

        "bench.title": "Сравнение методов на синтетических или реальных изображениях",
        "bench.images": "Изображения",
        "bench.synthetic": "Синтетические контейнеры",
        "bench.folder": "Папка с изображениями",
        "bench.count": "Количество изображений",
        "bench.size": "Размер синтетических контейнеров",
        "bench.payloads": "Нагрузка (бит на пиксель)",
        "bench.methods": "Методы",
        "bench.run": "Запустить сравнение",
        "bench.stop": "Остановить",
        "bench.export": "Экспорт CSV",
        "bench.progress": "Прогресс",
        "bench.col_method": "Метод",
        "bench.col_bpp": "бит/пиксель",
        "bench.col_psnr": "PSNR, дБ",
        "bench.col_ssim": "SSIM",
        "bench.col_spa": "SPA",
        "bench.col_time": "Встраивание, мс",
        "bench.col_recovered": "Восстановлено",
        "bench.done": "Сравнение завершено",
        "bench.cancelled": "Сравнение отменено",
        "bench.hint": "Меньшее значение SPA означает, что сообщение труднее "
                      "обнаружить при той же нагрузке",

        "about.title": "О программе stegolab",
        "about.description": "Исследовательский стенд по стеганографии и "
                             "стегоанализу изображений: контентно-адаптивное "
                             "встраивание в младшие биты, базовые методы, "
                             "метрики качества, атаки на контейнер и "
                             "классические детекторы.",
        "about.selftest": "Проверка детерминизма",
        "about.selftest_hint": "Запустите на двух машинах и сравните отпечаток: "
                               "одинаковые отпечатки означают, что обе сборки "
                               "совместимы между собой",
        "about.environment": "Окружение",
        "about.docs": "Документация и исходный код",
        "about.warning_title": "Чего программа не делает",
        "about.warning": "Сообщение не переживает пересохранение в JPEG, "
                         "масштабирование и шум. Стеганография скрывает сам "
                         "факт передачи; если нужно защитить содержание, "
                         "используйте пароль.",
    },
}

_current = DEFAULT_LANGUAGE


def available_languages() -> dict[str, str]:
    """Language code to native name."""
    return dict(LANGUAGES)


def detect_language() -> str:
    """Guess the interface language from the system locale.

    ``locale.getdefaultlocale`` is deprecated since Python 3.11, so the current
    locale is read first and the usual environment variables are used as a
    fallback. Both "en_US" and "Ukrainian_Ukraine" reduce to the right code.
    """
    candidates = []
    try:
        candidates.append(locale.getlocale()[0] or "")
    except (ValueError, TypeError):  # pragma: no cover - odd locale settings
        pass
    candidates += [os.environ.get("LANG", ""), os.environ.get("LC_ALL", "")]
    for value in candidates:
        code = (value or "")[:2].lower()
        if code in LANGUAGES:
            return code
    return DEFAULT_LANGUAGE


def load_preference() -> str:
    """Read the stored language, falling back to the detected one."""
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            code = json.load(f).get("language")
    except (OSError, ValueError):
        code = None
    return code if code in LANGUAGES else detect_language()


def save_preference(code: str) -> None:
    """Store the chosen language; failures are ignored on purpose."""
    try:
        data = {}
        if os.path.isfile(_CONFIG_PATH):
            with open(_CONFIG_PATH, encoding="utf-8") as f:
                data = json.load(f)
        data["language"] = code
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except (OSError, ValueError):  # pragma: no cover - read-only home, etc.
        pass


def set_language(code: str) -> str:
    """Switch the active language and return the code that took effect."""
    global _current
    _current = code if code in LANGUAGES else DEFAULT_LANGUAGE
    return _current


def get_language() -> str:
    """Currently active language code."""
    return _current


def translate(key: str, **kwargs) -> str:
    """Look up a key, falling back to English and then to the key itself."""
    text = _STRINGS.get(_current, {}).get(key)
    if text is None:
        text = _STRINGS[DEFAULT_LANGUAGE].get(key, key)
    return text.format(**kwargs) if kwargs else text
