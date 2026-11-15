# GeoForge

Дипломный прототип преобразования открытых геоданных в интерактивную 3D-сцену. Python-пайплайн загружает геоданные, переводит геометрию в локальную систему координат и экспортирует сцену в JSON. Импортёр на C# строит сцену в Unity. Генерация доступна из CLI и через HTTP API на FastAPI.

## Генерация сцены

Требуется Python 3.12. Для загрузки данных OpenStreetMap нужен интернет.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python -m app.cli --lat 44.6 --lon 33.5 --radius 500 --output-dir output/demo
```

Результат сохраняется в `output/demo/scene.json`. Для запуска HTTP API выполните `.\.venv\Scripts\python -m uvicorn app.api.main:app` и откройте [Swagger UI](http://127.0.0.1:8000/docs).

## Импорт в Unity

Откройте `unity/GeoForgeUnity` в Unity 6000.3.11f1. В сцене `Assets/GeoForge/Scenes/GeoForgeTest.unity` выберите объект GeoForge, укажите сохранённый `scene.json` в Scene Json Path и нажмите GenerateScene.

## Проверки

```powershell
.\.venv\Scripts\python -m pytest
```

Тесты проверяют преобразование координат, обработку геометрии, генерацию сцены и HTTP API. В папке Unity есть отдельные тесты редактора. Данные OpenStreetMap предоставляются участниками OpenStreetMap по [ODbL](https://www.openstreetmap.org/copyright). Лицензия LibTessDotNet находится рядом с исходниками библиотеки.
