## УСТАНОВКА И ЗАПУСК
версия python 3.11+ 
## Клонирование репозитория
git clone https://github.com/fuji1o/TeamPerformanceHub.git
cd TeamPerformanceHub

## Настройка бэкенда

### Создание виртуального окружения:

**Windows:**
cd backend
python -m venv venv
venv\Scripts\activate

**Mac/Linux:**
cd backend
python3 -m venv venv
source venv/bin/activate

### Установка зависимостей:
pip install -r requirements.txt

## Настройка переменных окружения

Скопируйте файл .env.example в .env:

**Windows:**
copy .env.example .env

**Mac/Linux:**
cp .env.example .env

Откройте файл .env и заполните свои данные:

### GitLab настройки
GITLAB_TOKEN=glpat-ваш_токен
GITLAB_URL=https://gitlab.com
GITLAB_PROJECT_IDS=80386581,81167879

### DeepSeek API
DEEPSEEK_API_KEY=sk-ваш_ключ
DEEPSEEK_BASE_URL=https://api.deepseek.com

## Запуск сервера
cd backend
python -m uvicorn main:app --reload

Сервер запустится на http://127.0.0.1:8000

## Запуск фронтенда
Откройте новый терминал:
cd frontend
python -m http.server 3000

Откройте браузер и перейдите по адресу: http://localhost:3000


## НАСТРОЙКА ПРОЕКТОВ

В файле .env укажите ID проектов GitLab через запятую:
GITLAB_PROJECT_IDS=80386581,81167879

### Как найти ID проекта в GitLab:
1. Откройте проект в GitLab
2. Перейдите в Settings → General
3. В разделе Project ID вы увидите числовой ID

### Примеры:
Один проект: GITLAB_PROJECT_IDS=80386581
Несколько проектов: GITLAB_PROJECT_IDS=80386581,81167879,81167880


## НАСТРОЙКА МАППИНГА ПОЛЬЗОВАТЕЛЕЙ

Если один разработчик в GitLab фигурирует под разными именами (например, Olesya в коммитах и Liccva в MR), их нужно объединить.

Создайте файл author_mapping.json в папке backend:

{
  "aliases": {
    "Olesya": "Liccva"
  },
  "primary_names": {
    "Liccva": {
      "display_name": "Olesya",
      "username": "Liccva",
      "emails": ["olesya@*"]
    },
    "fuji1o": {
      "display_name": "fuji1o",
      "username": "fuji1o",
      "emails": []
    }
  }
}

### Пример:
Если в GitLab коммиты подписаны как "Olesya", а MR создаёт пользователь "Liccva":
Добавьте в aliases: "Olesya": "Liccva"
Система объединит все данные под пользователем "Liccva"


## ВОЗМОЖНЫЕ ПРОБЛЕМЫ И РЕШЕНИЯ

### 1. Данные не загружаются в браузере
Откройте страницу в режиме инкогнито (Ctrl+Shift+N) — расширения браузера могут блокировать запросы к API

### 2. График не отображается
Убедитесь, что у выбранного разработчика есть коммиты за указанный период. Попробуйте выбрать период 90 дней.

### 3. Пустой список разработчиков
Проверьте, что в проекте есть коммиты за выбранный период. Убедитесь, что токен имеет доступ к проекту.