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

_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".adaptivestego.json")

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # -- window and tabs ------------------------------------------------
        "app.title": "AdaptiveStego - adaptive image steganography",
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
        "common.no_key_material": "Leave no password traces in the image",
        "common.no_key_material_hint": "The salt and the nonce are derived "
                                       "from the password instead of being "
                                       "stored, so nothing in the container "
                                       "shows that a password was used. The "
                                       "receiver needs only the password, as "
                                       "before.",
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
        "extract.not_found": "No container found with these settings",
        "extract.not_found_title": "Nothing found",
        "extract.not_found_hint": "The method, the key and the bits per "
                                  "sample must match the ones used for "
                                  "embedding. None of them are stored in the "
                                  "image, so a wrong setting looks exactly "
                                  "like an empty image.",
        "extract.found_size": "Found: {container} container, {message} message",
        "extract.found_compressed": "compressed",
        "extract.found_encrypted": "encrypted",
        "extract.found_maybe_encrypted": "probably encrypted, with no stored "
                                         "key material",
        "extract.found_ecc": "error correction {n}",
        "extract.password_title": "Password required",
        "extract.password_prompt_certain": "This message is encrypted. Enter "
                                           "the password:",
        "extract.password_prompt_suspected": "A container is there but does "
                                             "not read as a message, and it "
                                             "looks encrypted. Enter the "
                                             "password:",
        "extract.cancelled": "Cancelled",

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
        "analyze.rs": "RS estimate",
        "analyze.ws": "WS estimate",
        "analyze.hcf": "Calibrated HCF ratio",
        "analyze.deep_scan": "Search every method for a container",
        "analyze.overall": "Overall",
        "analyze.file_structure": "File structure",
        "analyze.format": "Format",
        "analyze.file_size": "File size",
        "analyze.file_clean": "nothing hidden in the file structure",
        "analyze.statistics_say": "The statistics say",
        "analyze.model": "Trained detector",
        "analyze.model_missing": "no model installed; train one with "
                                 "experiments/train_detector.py",
        "analyze.model_probability": "Probability of a payload",
        "analyze.model_trained": "Model",
        "analyze.model_scope": "Valid for",
        "analyze.containers": "Containers",
        "analyze.containers_none": "none found",
        "analyze.container_readable": "read in full",
        "analyze.container_locked": "found, not readable",
        "analyze.level_clean": "clean",
        "analyze.level_suspicious": "suspicious",
        "analyze.level_detected": "hidden data detected",
        "analyze.verdict_hint": "The statistical detectors see LSB "
                                "replacement; the trained model is what sees "
                                "LSB matching. A clean verdict at a low "
                                "payload means only that these tools found "
                                "nothing.",

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
        "about.title": "About AdaptiveStego",
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
        "app.title": "AdaptiveStego - адаптивна стеганографія зображень",
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
        "common.no_key_material": "Не лишати в зображенні слідів пароля",
        "common.no_key_material_hint": "Сіль і одноразове число виводяться з "
                                       "пароля, а не зберігаються, тож ніщо в "
                                       "контейнері не вказує, що пароль "
                                       "використано. Одержувачу, як і раніше, "
                                       "потрібен лише пароль.",
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
        "extract.not_found": "З цими параметрами контейнер не знайдено",
        "extract.not_found_title": "Нічого не знайдено",
        "extract.not_found_hint": "Метод, ключ і кількість бітів на відлік "
                                  "мають збігатися з тими, що були при "
                                  "вбудовуванні. Жоден із них не зберігається "
                                  "в зображенні, тож хибний параметр виглядає "
                                  "так само, як порожнє зображення.",
        "extract.found_size": "Знайдено: контейнер {container}, повідомлення "
                              "{message}",
        "extract.found_compressed": "стиснуте",
        "extract.found_encrypted": "зашифроване",
        "extract.found_maybe_encrypted": "ймовірно зашифроване, без збережених "
                                         "даних ключа",
        "extract.found_ecc": "корекція помилок {n}",
        "extract.password_title": "Потрібен пароль",
        "extract.password_prompt_certain": "Повідомлення зашифроване. Введіть "
                                           "пароль:",
        "extract.password_prompt_suspected": "Контейнер є, але не читається як "
                                             "повідомлення і має вигляд "
                                             "шифротексту. Введіть пароль:",
        "extract.cancelled": "Скасовано",

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
        "analyze.rs": "Оцінка RS",
        "analyze.ws": "Оцінка WS",
        "analyze.hcf": "Каліброване відношення HCF",
        "analyze.deep_scan": "Шукати контейнер усіма методами",
        "analyze.overall": "Загальний висновок",
        "analyze.file_structure": "Структура файлу",
        "analyze.format": "Формат",
        "analyze.file_size": "Розмір файлу",
        "analyze.file_clean": "у структурі файлу нічого не сховано",
        "analyze.statistics_say": "Статистика каже",
        "analyze.model": "Навчений детектор",
        "analyze.model_missing": "модель не встановлено; навчіть її через "
                                 "experiments/train_detector.py",
        "analyze.model_probability": "Ймовірність наявності даних",
        "analyze.model_trained": "Модель",
        "analyze.model_scope": "Дійсна для",
        "analyze.containers": "Контейнери",
        "analyze.containers_none": "не знайдено",
        "analyze.container_readable": "прочитано повністю",
        "analyze.container_locked": "знайдено, не читається",
        "analyze.level_clean": "чисто",
        "analyze.level_suspicious": "підозріло",
        "analyze.level_detected": "виявлено приховані дані",
        "analyze.verdict_hint": "Статистичні детектори бачать заміну "
                                "молодшого біта; LSB matching бачить лише "
                                "навчена модель. Висновок «чисто» на малому "
                                "навантаженні означає тільки те, що ці "
                                "інструменти нічого не знайшли.",

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

        "about.title": "Про AdaptiveStego",
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
        "app.title": "AdaptiveStego - адаптивная стеганография изображений",
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
        "common.no_key_material": "Не оставлять в изображении следов пароля",
        "common.no_key_material_hint": "Соль и одноразовое число выводятся из "
                                       "пароля, а не хранятся, поэтому ничто "
                                       "в контейнере не выдаёт, что пароль "
                                       "применялся. Получателю, как и раньше, "
                                       "нужен только пароль.",
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
        "extract.not_found": "С этими параметрами контейнер не найден",
        "extract.not_found_title": "Ничего не найдено",
        "extract.not_found_hint": "Метод, ключ и число бит на отсчёт должны "
                                  "совпадать с теми, что использовались при "
                                  "встраивании. Ни один из них не хранится в "
                                  "изображении, поэтому неверный параметр "
                                  "выглядит так же, как пустое изображение.",
        "extract.found_size": "Найдено: контейнер {container}, сообщение "
                              "{message}",
        "extract.found_compressed": "сжато",
        "extract.found_encrypted": "зашифровано",
        "extract.found_maybe_encrypted": "вероятно зашифровано, без сохранённых "
                                         "данных ключа",
        "extract.found_ecc": "коррекция ошибок {n}",
        "extract.password_title": "Требуется пароль",
        "extract.password_prompt_certain": "Сообщение зашифровано. Введите "
                                           "пароль:",
        "extract.password_prompt_suspected": "Контейнер есть, но не читается "
                                             "как сообщение и похож на "
                                             "шифротекст. Введите пароль:",
        "extract.cancelled": "Отменено",

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
        "analyze.rs": "Оценка RS",
        "analyze.ws": "Оценка WS",
        "analyze.hcf": "Калиброванное отношение HCF",
        "analyze.deep_scan": "Искать контейнер всеми методами",
        "analyze.overall": "Общий вывод",
        "analyze.file_structure": "Структура файла",
        "analyze.format": "Формат",
        "analyze.file_size": "Размер файла",
        "analyze.file_clean": "в структуре файла ничего не спрятано",
        "analyze.statistics_say": "Статистика говорит",
        "analyze.model": "Обученный детектор",
        "analyze.model_missing": "модель не установлена; обучите её через "
                                 "experiments/train_detector.py",
        "analyze.model_probability": "Вероятность наличия данных",
        "analyze.model_trained": "Модель",
        "analyze.model_scope": "Действительна для",
        "analyze.containers": "Контейнеры",
        "analyze.containers_none": "не найдено",
        "analyze.container_readable": "прочитан полностью",
        "analyze.container_locked": "найден, не читается",
        "analyze.level_clean": "чисто",
        "analyze.level_suspicious": "подозрительно",
        "analyze.level_detected": "обнаружены скрытые данные",
        "analyze.verdict_hint": "Статистические детекторы видят замену "
                                "младшего бита; LSB matching видит только "
                                "обученная модель. Вывод «чисто» при малой "
                                "нагрузке означает лишь то, что эти "
                                "инструменты ничего не нашли.",

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

        "about.title": "О программе AdaptiveStego",
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
