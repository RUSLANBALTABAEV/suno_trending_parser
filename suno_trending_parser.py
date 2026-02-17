# suno_trending_parser.py
# Парсер трендов Suno с ручным вводом SMS, скачиванием аудио и сохранением в SQLite

import time
import re
import os
import sqlite3
import requests
from urllib.parse import urljoin
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

# ==================== НАСТРОЙКИ ====================
DB_FILE = 'suno_trends.db'        # Файл базы данных SQLite
TABLE_NAME = 'tracks'
DOWNLOAD_DIR = 'downloads'         # Папка для сохранения музыки

# Создаём папку для скачивания, если её нет
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ==================== ФУНКЦИИ ДЛЯ РАБОТЫ С БД ====================

def create_database_and_table():
    """Создаёт файл базы данных и таблицу, если они не существуют,
       а также добавляет недостающие колонки."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # 1. Создаём таблицу, если её нет (минимальная структура)
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artist TEXT,
                title TEXT,
                track_url TEXT UNIQUE,
                audio_url TEXT,
                plays INTEGER DEFAULT 0,
                explicit INTEGER DEFAULT 0,
                file_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

        # 2. Проверяем наличие всех нужных колонок и добавляем отсутствующие
        cursor.execute(f"PRAGMA table_info({TABLE_NAME})")
        existing_columns = [col[1] for col in cursor.fetchall()]
        required_columns = [
            ('artist', 'TEXT'),
            ('title', 'TEXT'),
            ('track_url', 'TEXT UNIQUE'),
            ('audio_url', 'TEXT'),
            ('plays', 'INTEGER DEFAULT 0'),
            ('explicit', 'INTEGER DEFAULT 0'),
            ('file_path', 'TEXT'),
            ('created_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
        ]

        for col_name, col_def in required_columns:
            if col_name not in existing_columns:
                try:
                    cursor.execute(f"ALTER TABLE {TABLE_NAME} ADD COLUMN {col_name} {col_def}")
                    print(f"➕ Добавлена колонка {col_name}")
                except Exception as e:
                    print(f"⚠️ Не удалось добавить колонку {col_name}: {e}")

        conn.commit()
        conn.close()
        print("✅ База данных SQLite и таблица проверены/созданы.")
    except Exception as e:
        print(f"❌ Ошибка при работе с SQLite: {e}")
        exit(1)

def get_db_connection():
    """Возвращает соединение с базой данных SQLite."""
    return sqlite3.connect(DB_FILE)

def track_exists(cursor, track_url):
    """Проверяет, есть ли трек с таким URL в базе."""
    cursor.execute(f"SELECT id FROM {TABLE_NAME} WHERE track_url = ?", (track_url,))
    return cursor.fetchone() is not None

# ==================== ФУНКЦИИ ДЛЯ РАБОТЫ С ФАЙЛАМИ ====================

def sanitize_filename(filename):
    """Удаляет недопустимые для имени файла символы."""
    return re.sub(r'[\\/*?:"<>|]', "", filename).strip()

def download_audio(url, artist, title):
    """
    Скачивает аудиофайл по URL.
    Возвращает путь к сохранённому файлу или None в случае ошибки.
    """
    if not url:
        return None

    filename = sanitize_filename(f"{artist} - {title}.mp3")
    filepath = os.path.join(DOWNLOAD_DIR, filename)

    # Если файл уже существует, не качаем заново
    if os.path.exists(filepath):
        print(f"  ⏩ Файл уже существует: {filepath}")
        return filepath

    try:
        print(f"  ⬇️ Скачивание: {url}")
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        r = requests.get(url, stream=True, timeout=45, headers=headers)
        r.raise_for_status()

        # Проверяем Content-Type, чтобы убедиться, что это аудио
        content_type = r.headers.get('Content-Type', '')
        if 'audio' not in content_type and 'octet-stream' not in content_type:
            print(f"  ⚠️ URL ведёт не на аудиофайл ({content_type}), пропускаем.")
            return None

        with open(filepath, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"  ✅ Сохранено: {filepath}")
        return filepath
    except Exception as e:
        print(f"  ❌ Ошибка скачивания {url}: {e}")
        return None

# ==================== ОСНОВНАЯ ФУНКЦИЯ ПАРСИНГА ====================

def parse_trending(max_tracks=50):
    """
    Основная функция.
    1. Открывает браузер.
    2. Ждёт ручного входа (номер, SMS).
    3. Переходит на /trending, собирает данные о треках.
    4. Для каждого нового трека переходит на его страницу и скачивает аудио.
    Возвращает список словарей с данными о треках.
    """
    options = webdriver.ChromeOptions()
    # options.add_argument('--headless=new')  # Раскомментируйте для работы в фоне
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36')

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    tracks_data = []

    try:
        # --- ШАГ 1: Ручной вход ---
        print("\n=== ЭТАП 1: Вход в аккаунт ===")
        driver.get('https://suno.com/sign-in')
        print("1️⃣ В открывшемся окне браузера введите ваш номер телефона.")
        print("2️⃣ Нажмите 'Continue' и введите код из SMS, когда он придёт.")
        print("3️⃣ После успешного входа и появления главной страницы нажмите Enter здесь.")
        input("⏸️ Ожидание... Нажмите Enter, когда войдёте в аккаунт.")

        # --- ШАГ 2: Переход на страницу трендов ---
        print("\n=== ЭТАП 2: Парсинг страницы трендов ===")
        trending_url = 'https://suno.com/trending'
        print(f"Загружаем: {trending_url}")
        driver.get(trending_url)

        WebDriverWait(driver, 40).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="song-row"]'))
        )

        # Скроллим для подгрузки всех треков
        print("Скроллим страницу для загрузки треков...")
        last_height = driver.execute_script("return document.body.scrollHeight")
        for i in range(15):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(3)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                print("  Достигнут конец страницы.")
                break
            last_height = new_height
            print(f"  Скролл {i+1}...")

        # Сохраняем HTML для отладки
        debug_file = f"debug_trending_{int(time.time())}.html"
        with open(debug_file, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print(f"📁 Отладочный HTML сохранён: {debug_file}")

        # Парсим блоки треков
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        song_blocks = soup.find_all('div', attrs={'data-testid': 'song-row'})
        print(f"Найдено блоков треков: {len(song_blocks)}")

        # --- ШАГ 3: Извлечение данных из каждого блока ---
        for index, block in enumerate(song_blocks[:max_tracks]):
            print(f"\n--- Трек {index+1} ---")

            title_tag = block.find('a', href=re.compile(r'^/song/'))
            title = title_tag.get_text(strip=True) if title_tag else 'Untitled'

            author_tag = block.find('a', href=re.compile(r'^/@'))
            artist = author_tag.get_text(strip=True) if author_tag else 'Unknown'

            track_url = None
            if title_tag and title_tag.has_attr('href'):
                track_url = urljoin('https://suno.com', title_tag['href'])

            plays = 0
            plays_tag = block.find('button', attrs={'aria-label': 'Play Count'})
            if plays_tag:
                plays_text = plays_tag.get_text(strip=True)
                match = re.match(r'([\d.]+)([KM]?)', plays_text.upper())
                if match:
                    val, suffix = match.groups()
                    mult = 1000 if suffix == 'K' else 1000000 if suffix == 'M' else 1
                    plays = int(float(val) * mult)

            explicit = False  # на странице трендов нет, можно не использовать

            print(f"  👤 Автор: {artist}")
            print(f"  🎵 Название: {title}")
            print(f"  🔗 Ссылка: {track_url}")
            print(f"  ▶️ Прослушиваний: {plays}")

            track_info = {
                'artist': artist,
                'title': title,
                'track_url': track_url,
                'plays': plays,
                'explicit': explicit,
                'audio_url': None,
                'file_path': None
            }
            tracks_data.append(track_info)

        # --- ШАГ 4: Переход на страницы треков для скачивания аудио ---
        print("\n=== ЭТАП 3: Получение и скачивание аудио ===")
        conn = get_db_connection()
        cursor = conn.cursor()

        for track in tracks_data:
            if not track['track_url']:
                print("  ⚠️ Пропуск: нет ссылки на трек.")
                continue

            if track_exists(cursor, track['track_url']):
                print(f"  ⏩ Трек '{track['title']}' уже есть в базе, пропускаем.")
                continue

            print(f"\n  Обрабатываем: {track['artist']} - {track['title']}")
            print(f"  Переход на страницу трека: {track['track_url']}")

            try:
                driver.get(track['track_url'])
                time.sleep(5)

                audio_soup = BeautifulSoup(driver.page_source, 'html.parser')

                # Поиск реального аудио (сначала в скриптах, потом в теге audio)
                audio_url = None

                # 1. Ищем в скриптах
                scripts = audio_soup.find_all('script')
                for script in scripts:
                    if script.string:
                        urls = re.findall(r'(https?://[^\s\'"<>]+\.(mp3|wav|ogg|m4a|flac))', script.string, re.I)
                        if urls:
                            real_url = urls[0][0]
                            if 'sil-100.mp3' not in real_url:
                                audio_url = real_url
                                print(f"    🎧 Найдено в скрипте: {audio_url[:100]}...")
                                break

                # 2. Если не нашли, проверяем audio-тег
                if not audio_url:
                    audio_tag = audio_soup.find('audio', src=re.compile(r'\.(mp3|wav|ogg|m4a|flac)$', re.I))
                    if audio_tag and audio_tag.has_attr('src'):
                        potential_url = audio_tag['src']
                        if 'sil-100.mp3' not in potential_url:
                            audio_url = potential_url
                            print(f"    🎧 Найден аудио-тег: {audio_url[:100]}...")
                        else:
                            print("    ⚠️ Аудио-тег содержит заглушку, пропускаем.")

                track['audio_url'] = audio_url

                if track['audio_url']:
                    track['file_path'] = download_audio(track['audio_url'], track['artist'], track['title'])
                else:
                    print("    ❌ Ссылка на аудио не найдена.")

            except Exception as e:
                print(f"    ❌ Ошибка при обработке страницы трека: {e}")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"❌ Критическая ошибка парсинга: {e}")
    finally:
        driver.quit()
        print("\n🔚 Браузер закрыт.")

    return tracks_data

# ==================== ФУНКЦИЯ СОХРАНЕНИЯ В БД ====================

def save_new_tracks(tracks):
    """Сохраняет только новые треки в базу данных SQLite."""
    if not tracks:
        return []

    conn = get_db_connection()
    cursor = conn.cursor()
    new_tracks = []

    for track in tracks:
        if track['track_url'] and not track_exists(cursor, track['track_url']):
            try:
                cursor.execute(f"""
                    INSERT INTO {TABLE_NAME}
                    (artist, title, track_url, audio_url, plays, explicit, file_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    track['artist'], track['title'], track['track_url'],
                    track['audio_url'], track['plays'], 1 if track['explicit'] else 0,
                    track['file_path']
                ))
                conn.commit()
                new_tracks.append(track)
                print(f"  ✅ Сохранено в БД: {track['artist']} - {track['title']}")
            except sqlite3.IntegrityError:
                print(f"  ⚠️ Трек {track['track_url']} уже существует (уникальность).")
            except Exception as e:
                print(f"  ❌ Ошибка сохранения в БД для {track['track_url']}: {e}")

    cursor.close()
    conn.close()
    return new_tracks

# ==================== ЗАПУСК ====================

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 Suno Trending Parser (SQLite + скачивание)")
    print("=" * 60)

    create_database_and_table()
    all_tracks = parse_trending(max_tracks=50)

    print("\n" + "=" * 60)
    print("💾 Сохранение новых треков в базу данных...")
    new_tracks_saved = save_new_tracks(all_tracks)

    print("\n" + "=" * 60)
    print(f"📊 Всего обработано треков: {len(all_tracks)}")
    print(f"✨ Новых треков добавлено в БД: {len(new_tracks_saved)}")
    print("=" * 60)
