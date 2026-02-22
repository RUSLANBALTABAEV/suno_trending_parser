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
                styles_preview TEXT,
                styles_full TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

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
            ('styles_preview', 'TEXT'),
            ('styles_full', 'TEXT'),
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
    return sqlite3.connect(DB_FILE)

def track_exists(cursor, track_url):
    cursor.execute(f"SELECT id FROM {TABLE_NAME} WHERE track_url = ?", (track_url,))
    return cursor.fetchone() is not None

# ==================== ФУНКЦИИ ДЛЯ РАБОТЫ С ФАЙЛАМИ ====================

def sanitize_filename(filename):
    return re.sub(r'[\\/*?:"<>|]', "", filename).strip()

def download_audio(url, artist, title):
    if not url:
        return None

    filename = sanitize_filename(f"{artist} - {title}.mp3")
    filepath = os.path.join(DOWNLOAD_DIR, filename)

    if os.path.exists(filepath):
        print(f"  ⏩ Файл уже существует: {filepath}")
        return filepath

    try:
        print(f"  ⬇️ Скачивание: {url}")
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        r = requests.get(url, stream=True, timeout=45, headers=headers)
        r.raise_for_status()

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
    options = webdriver.ChromeOptions()
    # options.add_argument('--headless=new')  # раскомментировать для фонового режима
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
        print("1️⃣ Введите номер телефона в браузере")
        print("2️⃣ Введите код из SMS")
        print("3️⃣ После входа нажмите Enter здесь")
        input("⏸️ Ожидание... Нажмите Enter после входа")

        # --- ШАГ 2: Парсинг трендов ---
        print("\n=== ЭТАП 2: Парсинг страницы трендов ===")
        trending_url = 'https://suno.com/trending'
        print(f"Загружаем: {trending_url}")
        driver.get(trending_url)

        WebDriverWait(driver, 40).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="song-row"]'))
        )

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

        debug_file = f"debug_trending_{int(time.time())}.html"
        with open(debug_file, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print(f"📁 Отладочный HTML: {debug_file}")

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        song_blocks = soup.find_all('div', attrs={'data-testid': 'song-row'})
        print(f"Найдено блоков треков: {len(song_blocks)}")

        for index, block in enumerate(song_blocks[:max_tracks]):
            print(f"\n--- Трек {index+1} ---")

            title_tag = block.find('a', href=re.compile(r'^/song/'))
            title = title_tag.get_text(strip=True) if title_tag else 'Untitled'

            author_tag = block.find('a', href=re.compile(r'^/@'))
            artist = author_tag.get_text(strip=True) if author_tag else 'Unknown'

            track_url = urljoin('https://suno.com', title_tag['href']) if title_tag and title_tag.has_attr('href') else None

            plays = 0
            plays_tag = block.find('button', attrs={'aria-label': 'Play Count'})
            if plays_tag:
                plays_text = plays_tag.get_text(strip=True)
                match = re.match(r'([\d.]+)([KM]?)', plays_text.upper())
                if match:
                    val, suffix = match.groups()
                    mult = 1000 if suffix == 'K' else 1000000 if suffix == 'M' else 1
                    plays = int(float(val) * mult)

            print(f"  👤 Автор: {artist}")
            print(f"  🎵 Название: {title}")
            print(f"  🔗 Ссылка: {track_url}")
            print(f"  ▶️ Прослушиваний: {plays}")

            tracks_data.append({
                'artist': artist,
                'title': title,
                'track_url': track_url,
                'plays': plays,
                'explicit': False,
                'audio_url': None,
                'file_path': None,
                'styles_preview': None,
                'styles_full': None
            })

        # --- ШАП 3: Обработка страниц треков ---
        print("\n=== ЭТАП 3: Получение аудио и стилей ===")
        conn = get_db_connection()
        cursor = conn.cursor()

        for track in tracks_data:
            if not track['track_url']:
                print("  ⚠️ Пропуск: нет ссылки")
                continue

            if track_exists(cursor, track['track_url']):
                print(f"  ⏩ Уже в базе: {track['title']}")
                continue

            print(f"\n  Обрабатываем: {track['artist']} - {track['title']}")
            driver.get(track['track_url'])
            time.sleep(4)  # даём странице загрузиться

            # ─── Поиск стилей (защищённый блок) ───
            try:
                style_container = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located(
                        (By.XPATH, "//*[.//a[contains(@href, '/style/')]]")
                    )
                )

                style_links = style_container.find_elements(By.XPATH, ".//a[contains(@href, '/style/')]")
                preview = ', '.join(link.text.strip() for link in style_links if link.text.strip())
                track['styles_preview'] = preview if preview else None

                try:
                    show_button = style_container.find_element(
                        By.XPATH,
                        ".//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'show full') or contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'full styles')]"
                    )
                    driver.execute_script("arguments[0].click();", show_button)
                    time.sleep(2)

                    all_style_links = style_container.find_elements(By.XPATH, ".//a[contains(@href, '/style/')]")
                    full = ', '.join(link.text.strip() for link in all_style_links if link.text.strip())
                    track['styles_full'] = full if full else preview
                except:
                    track['styles_full'] = preview

                if track['styles_preview']:
                    print(f"    🏷️ Стили (preview): {track['styles_preview'][:100]}{'...' if len(track['styles_preview']) > 100 else ''}")
                if track['styles_full'] and track['styles_full'] != track['styles_preview']:
                    print(f"    🏷️ Стили (full):   {track['styles_full'][:100]}{'...' if len(track['styles_full']) > 100 else ''}")

            except Exception:
                # Тихо пропускаем — стили просто останутся None
                pass

            # ─── Поиск аудио ───
            audio_soup = BeautifulSoup(driver.page_source, 'html.parser')
            audio_url = None

            scripts = audio_soup.find_all('script')
            for script in scripts:
                if script.string:
                    urls = re.findall(r'(https?://[^\s\'"<>]+\.(mp3|wav|ogg|m4a|flac))', script.string, re.I)
                    if urls:
                        real_url = urls[0][0]
                        if 'sil-100.mp3' not in real_url:
                            audio_url = real_url
                            break

            if not audio_url:
                audio_tag = audio_soup.find('audio', src=re.compile(r'\.(mp3|wav|ogg|m4a|flac)$', re.I))
                if audio_tag and audio_tag.has_attr('src'):
                    potential = audio_tag['src']
                    if 'sil-100.mp3' not in potential:
                        audio_url = potential

            track['audio_url'] = audio_url

            if audio_url:
                print(f"    🎧 Аудио: {audio_url[:80]}...")
                track['file_path'] = download_audio(audio_url, track['artist'], track['title'])
            else:
                print("    ❌ Аудио не найдено")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
    finally:
        driver.quit()
        print("\n🔚 Браузер закрыт.")

    return tracks_data

# ==================== СОХРАНЕНИЕ В БД ====================

def save_new_tracks(tracks):
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
                    (artist, title, track_url, audio_url, plays, explicit, file_path, styles_preview, styles_full)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    track['artist'], track['title'], track['track_url'],
                    track['audio_url'], track['plays'], 1 if track['explicit'] else 0,
                    track['file_path'], track['styles_preview'], track['styles_full']
                ))
                conn.commit()
                new_tracks.append(track)
                print(f"  ✅ Добавлено в БД: {track['artist']} - {track['title']}")
            except sqlite3.IntegrityError:
                pass
            except Exception as e:
                print(f"  ❌ Ошибка сохранения {track['track_url']}: {e}")

    cursor.close()
    conn.close()
    return new_tracks

# ==================== ЗАПУСК ====================

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 Suno Trending Parser (SQLite + download + styles)")
    print("=" * 60)

    create_database_and_table()
    all_tracks = parse_trending(max_tracks=50)

    print("\n" + "=" * 60)
    print("💾 Сохранение новых треков...")
    new_saved = save_new_tracks(all_tracks)

    print("\n" + "=" * 60)
    print(f"📊 Обработано треков: {len(all_tracks)}")
    print(f"✨ Новых добавлено: {len(new_saved)}")
    print("=" * 60)
