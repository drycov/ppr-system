"""Инициализация БД: шаблоны из Положения ОСС + импорт объектов из Excel"""
from datetime import date, datetime, timedelta
from sqlalchemy.orm import Session
from database import SessionLocal, engine, Base
from models import Object, PPRTemplate, PPRPlan, User, DailyCheck
import openpyxl
from pathlib import Path

# Путь к отчётам
ATTACHMENTS = Path("/home/workdir/attachments")


def create_tables():
    Base.metadata.create_all(bind=engine)


def seed_templates(db: Session):
    """Шаблоны из Положения ОСС ППР + виды работ АПК"""
    templates = [
        # === Положение ОСС ===
        {
            "code": "1",
            "name": "Маршрутизаторы и коммутаторы (MikroTik, Cisco и др.)",
            "description": "Очистка от пыли, проверка вентиляторов и температурного режима, контроль индикации, проверка креплений",
            "object_types": ["network"],
            "work_items": ["Очистка от пыли", "Проверка вентиляторов", "Контроль температуры", "Проверка креплений"],
            "periodicity": "quarterly",
            "responsible_role": "engineer",
        },
        {
            "code": "2",
            "name": "Активное сетевое оборудование — аудит конфигураций",
            "description": "Аудит конфигураций, проверка и обновление резервных копий конфигураций, анализ логов",
            "object_types": ["network"],
            "work_items": ["Аудит конфигураций", "Проверка бэкапов", "Анализ логов"],
            "periodicity": "monthly",
            "responsible_role": "engineer",
        },
        {
            "code": "3",
            "name": "Серверы сетевых служб (DNS, DHCP, мониторинг, контроллеры)",
            "description": "Проверка состояния дисков, RAID-массивов, обновление ПО, очистка временных файлов, контроль температуры",
            "object_types": ["network"],
            "work_items": ["Проверка дисков/RAID", "Обновление ПО", "Очистка temp", "Контроль температуры"],
            "periodicity": "quarterly",
            "responsible_role": "engineer",
        },
        {
            "code": "4",
            "name": "Источники бесперебойного питания (ИБП)",
            "description": "Тестирование батарей, проверка автономии, очистка, контроль состояния АКБ, калибровка",
            "object_types": ["network"],
            "work_items": ["Тест батарей", "Проверка автономии", "Очистка", "Калибровка"],
            "periodicity": "semi_annual",
            "responsible_role": "engineer",
        },
        {
            "code": "5",
            "name": "Системы VPN, туннели, HotSpot",
            "description": "Проверка работоспособности туннелей, анализ журналов подключений, тестирование резервных каналов",
            "object_types": ["network"],
            "work_items": ["Проверка туннелей", "Анализ логов подключений", "Тест резервных каналов"],
            "periodicity": "monthly",
            "responsible_role": "engineer",
        },
        {
            "code": "6",
            "name": "Межсетевые экраны (Firewall) и системы безопасности",
            "description": "Аудит правил фильтрации, обновление сигнатур, анализ событий безопасности",
            "object_types": ["network"],
            "work_items": ["Аудит правил", "Обновление сигнатур", "Анализ событий"],
            "periodicity": "monthly",
            "responsible_role": "engineer",
        },
        {
            "code": "7",
            "name": "Структурированная кабельная система (СКС)",
            "description": "Визуальный осмотр, проверка маркировки, тестирование критичных линий, устранение повреждений",
            "object_types": ["network"],
            "work_items": ["Визуальный осмотр", "Проверка маркировки", "Тестирование линий"],
            "periodicity": "annual",
            "responsible_role": "engineer",
        },
        {
            "code": "8",
            "name": "Точки доступа Wi-Fi",
            "description": "Проверка покрытия, анализ загруженности каналов, обновление прошивок, очистка оборудования",
            "object_types": ["network"],
            "work_items": ["Проверка покрытия", "Анализ загрузки", "Обновление прошивок", "Очистка"],
            "periodicity": "quarterly",
            "responsible_role": "engineer",
        },
        {
            "code": "9",
            "name": "Системы мониторинга сети (Zabbix)",
            "description": "Проверка агентов, актуализация шаблонов, анализ ложных срабатываний, проверка оповещений",
            "object_types": ["network"],
            "work_items": ["Проверка агентов", "Актуализация шаблонов", "Анализ false positive", "Проверка оповещений"],
            "periodicity": "monthly",
            "responsible_role": "engineer",
        },
        {
            "code": "10",
            "name": "Программное обеспечение сетевого оборудования",
            "description": "Проверка наличия обновлений прошивок и ПО, планирование и выполнение безопасных обновлений",
            "object_types": ["network"],
            "work_items": ["Проверка обновлений", "Планирование", "Выполнение обновлений"],
            "periodicity": "quarterly",
            "responsible_role": "engineer",
        },
        {
            "code": "11",
            "name": "Резервные каналы связи и резервирование",
            "description": "Тестирование переключения на резерв, проверка SLA провайдеров, анализ доступности",
            "object_types": ["network"],
            "work_items": ["Тест failover", "Проверка SLA", "Анализ доступности"],
            "periodicity": "quarterly",
            "responsible_role": "engineer",
        },
        {
            "code": "12",
            "name": "Инвентаризация сетевого оборудования",
            "description": "Полная инвентаризация, сверка с учётными данными, актуализация схем и документации",
            "object_types": ["network"],
            "work_items": ["Инвентаризация", "Сверка учёта", "Актуализация схем"],
            "periodicity": "annual",
            "responsible_role": "head",
        },
        # === Виды работ АПК (камеры) ===
        {
            "code": "7.5",
            "name": "Юстировка камер",
            "description": "Юстировка (настройка угла обзора) камер видеонаблюдения",
            "object_types": ["camera_integration", "ovn"],
            "work_items": ["Юстировка камер"],
            "periodicity": "monthly",
            "responsible_role": "engineer",
        },
        {
            "code": "7.6",
            "name": "Проверка надёжности крепления камер",
            "description": "Проверка надёжности крепления камер",
            "object_types": ["camera_integration", "ovn"],
            "work_items": ["Проверка крепления камер"],
            "periodicity": "monthly",
            "responsible_role": "engineer",
        },
        {
            "code": "7.7",
            "name": "Проверка надёжности крепления коммутационного шкафа",
            "description": "Проверка крепления коммутационного шкафа",
            "object_types": ["camera_integration", "ovn"],
            "work_items": ["Проверка крепления шкафа"],
            "periodicity": "monthly",
            "responsible_role": "engineer",
        },
        {
            "code": "7.8",
            "name": "Обслуживание кабельных линий UTP",
            "description": "Обслуживание кабельных линий UTP, проверка провисов, укладка запасов",
            "object_types": ["camera_integration", "ovn"],
            "work_items": ["Проверка провисов UTP", "Укладка запасов"],
            "periodicity": "monthly",
            "responsible_role": "engineer",
        },
        {
            "code": "9.2",
            "name": "ППР камер (вид 9.2)",
            "description": "Регламентные работы по камерам интеграции (вид 9.2)",
            "object_types": ["camera_integration"],
            "work_items": ["9.2"],
            "periodicity": "monthly",
            "responsible_role": "engineer",
        },
        {
            "code": "9.3",
            "name": "ППР камер (вид 9.3)",
            "description": "Регламентные работы по камерам интеграции (вид 9.3)",
            "object_types": ["camera_integration"],
            "work_items": ["9.3"],
            "periodicity": "monthly",
            "responsible_role": "engineer",
        },
        # === ВОЛС ===
        {
            "code": "11.1-11.6",
            "name": "ППР ВОЛС",
            "description": "Планово-профилактические работы на волоконно-оптических линиях связи",
            "object_types": ["voles"],
            "work_items": ["11.1", "11.2", "11.3", "11.4", "11.5", "11.6"],
            "periodicity": "twice_year",
            "responsible_role": "engineer",
        },
    ]

    for t in templates:
        existing = db.query(PPRTemplate).filter(PPRTemplate.code == t["code"]).first()
        if not existing:
            db.add(PPRTemplate(**t))
    db.commit()
    print(f"✓ Шаблоны ППР загружены: {len(templates)}")


def seed_users(db: Session):
    """Сотрудники из отчётов ППР + руководство"""
    users = [
        {"username": "admin", "full_name": "Рыков Д.И.", "role": "admin", "position": "Начальник ОСС", "hashed_password": "admin", "can_do_ppr": True, "can_duty": True},
        {"username": "head", "full_name": "Начальник ОСС", "role": "head", "position": "Начальник ОСС", "hashed_password": "head", "can_do_ppr": True, "can_duty": False},
        {"username": "kuryanov", "full_name": "Курьянов Олег Константинович", "role": "engineer", "position": "Инженер ОСС", "hashed_password": "eng", "can_do_ppr": True, "can_duty": True},
        {"username": "leskin", "full_name": "Лескин Александр Александрович", "role": "engineer", "position": "Инженер ОСС", "hashed_password": "eng", "can_do_ppr": True, "can_duty": True},
        {"username": "mazhrenov", "full_name": "Мажренов Марат Кланович", "role": "engineer", "position": "Инженер ОСС", "hashed_password": "eng", "can_do_ppr": True, "can_duty": True},
        {"username": "murzamuhametov", "full_name": "Мурзамұхаметов Олжас Нұржанұлы", "role": "engineer", "position": "Инженер ОСС", "hashed_password": "eng", "can_do_ppr": True, "can_duty": True},
        {"username": "murat", "full_name": "Мұрат Нұрлан", "role": "engineer", "position": "Инженер ОСС", "hashed_password": "eng", "can_do_ppr": True, "can_duty": True},
        {"username": "nurahmetov", "full_name": "Нурахметов Алтынбек Ержанулы", "role": "engineer", "position": "Инженер ОСС", "hashed_password": "eng", "can_do_ppr": True, "can_duty": True},
        {"username": "pashaev", "full_name": "Пашаев Вагиф Салехович", "role": "engineer", "position": "Инженер ОСС", "hashed_password": "eng", "can_do_ppr": True, "can_duty": True},
        {"username": "sidorenko", "full_name": "Сидоренко Сергей Юрьевич", "role": "engineer", "position": "Инженер ОСС", "hashed_password": "eng", "can_do_ppr": True, "can_duty": True},
        {"username": "shalakin", "full_name": "Шалакин Дмитрий Александрович", "role": "engineer", "position": "Инженер ОСС", "hashed_password": "eng", "can_do_ppr": True, "can_duty": True},
        {"username": "belotserkovsky", "full_name": "Белоцерковский Ярослав Константинович", "role": "engineer", "position": "Инженер ОСС", "hashed_password": "eng", "can_do_ppr": True, "can_duty": True},
        {"username": "bolenkanuly", "full_name": "Бөленқанұлы Айбек", "role": "engineer", "position": "Инженер ОСС", "hashed_password": "eng", "can_do_ppr": True, "can_duty": True},
        {"username": "dadaev", "full_name": "Дадаев Руслан Руманович", "role": "engineer", "position": "Инженер ОСС", "hashed_password": "eng", "can_do_ppr": True, "can_duty": True},
        {"username": "zhansoltanov", "full_name": "Жансолтанов Олжас Миратұлы", "role": "engineer", "position": "Инженер ОСС", "hashed_password": "eng", "can_do_ppr": True, "can_duty": True},
        {"username": "zhanibekov", "full_name": "Жәнібеков Бауыржан Әділұлы", "role": "engineer", "position": "Инженер ОСС", "hashed_password": "eng", "can_do_ppr": True, "can_duty": True},
        {"username": "kazantsev", "full_name": "Казанцев Александр Дмитриевич", "role": "engineer", "position": "Инженер ОСС", "hashed_password": "eng", "can_do_ppr": True, "can_duty": True},
        {"username": "kaisanov", "full_name": "Кайсанов Шынгыс Нуржанович", "role": "engineer", "position": "Инженер ОСС", "hashed_password": "eng", "can_do_ppr": True, "can_duty": True},
        {"username": "kasymov", "full_name": "Қасымов Дияс Нұрболатұлы", "role": "engineer", "position": "Инженер ОСС", "hashed_password": "eng", "can_do_ppr": True, "can_duty": True},
        {"username": "kydyrhanov", "full_name": "Қыдырханов Оңдасын", "role": "engineer", "position": "Инженер ОСС", "hashed_password": "eng", "can_do_ppr": True, "can_duty": True},
        {"username": "sagymzhanov", "full_name": "Сағымжанов Бекзат Болатұлы", "role": "engineer", "position": "Инженер ОСС", "hashed_password": "eng", "can_do_ppr": True, "can_duty": True},
        {"username": "samarhanov", "full_name": "Самарханов Айбек Сергеевич", "role": "engineer", "position": "Инженер ОСС", "hashed_password": "eng", "can_do_ppr": True, "can_duty": True},
        {"username": "baibagysov", "full_name": "Байбагысов Айдын Нурлыбекович", "role": "engineer", "position": "Инженер ОСС", "hashed_password": "eng", "can_do_ppr": True, "can_duty": True},
        {"username": "klanov", "full_name": "Қланов Мирас Маратұлы", "role": "engineer", "position": "Инженер ОСС", "hashed_password": "eng", "can_do_ppr": True, "can_duty": True},
    ]
    for u in users:
        existing = db.query(User).filter(User.username == u["username"]).first()
        if not existing:
            db.add(User(**u))
        else:
            for k, v in u.items():
                if k != "hashed_password":
                    setattr(existing, k, v)
    db.commit()
    print(f"✓ Сотрудники: {db.query(User).count()}")


def import_integration_objects(db: Session):
    """Импорт объектов ИНТ из отчёта"""
    xlsx_path = ATTACHMENTS / "Отчет_ППР_АПК_СЕНТЯБРЬ_2026г..xlsx"
    if not xlsx_path.exists():
        print("⚠ Файл отчёта не найден")
        return

    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb["ППР (ИНТЕГ),"]

    count = 0
    for row in ws.iter_rows(min_row=4, max_row=300, max_col=9, values_only=True):
        num, code, address, cameras, responsible, ppr_date, period, status, work_types = row[:9]
        if not code or not str(code).startswith("ИНТ"):
            continue
        code = str(code).strip()
        if db.query(Object).filter(Object.code == code).first():
            continue

        try:
            cams = int(cameras) if cameras and str(cameras).isdigit() else 0
        except Exception:
            cams = 0

        obj = Object(
            code=code,
            name=str(address)[:100] if address else code,
            address=str(address) if address else None,
            object_type="camera_integration",
            cameras_count=cams,
            status="active",
            responsible_default=str(responsible) if responsible else None,
            notes=None,
        )
        db.add(obj)
        count += 1

        # Если есть дата и статус — создаём запись плана
        if ppr_date and status:
            db.flush()
            plan = PPRPlan(
                object_id=obj.id,
                title=f"ППР {code}",
                planned_date=ppr_date.date() if hasattr(ppr_date, "date") else date(2025, 12, 1),
                fact_date=ppr_date.date() if hasattr(ppr_date, "date") else None,
                responsible=str(responsible) if responsible else None,
                status="done" if "исполнено" in str(status).lower() else "planned",
                work_types_done=str(work_types).split(", ") if work_types else [],
            )
            db.add(plan)

    db.commit()
    print(f"✓ Импортировано объектов ИНТ: {count}")


def import_voles_objects(db: Session):
    """Импорт ВОЛС"""
    xlsx_path = ATTACHMENTS / "Отчет_ППР_АПК_СЕНТЯБРЬ_2026г..xlsx"
    if not xlsx_path.exists():
        return

    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    if "ППР (ВОЛС) г.Ука" not in wb.sheetnames:
        return
    ws = wb["ППР (ВОЛС) г.Ука"]

    count = 0
    for row in ws.iter_rows(min_row=4, max_row=260, max_col=7, values_only=True):
        num, address, responsible, ppr_date, period, status, note = row[:7]
        if not address:
            continue
        code = f"ВОЛС-{num}" if num else f"ВОЛС-{count+1}"
        if db.query(Object).filter(Object.code == code).first():
            continue

        obj = Object(
            code=code,
            name=str(address)[:100],
            address=str(address),
            object_type="voles",
            cameras_count=0,
            status="active",
            responsible_default=str(responsible) if responsible else None,
        )
        db.add(obj)
        count += 1

        if ppr_date and status:
            db.flush()
            plan = PPRPlan(
                object_id=obj.id,
                title=f"ППР ВОЛС {address}",
                planned_date=ppr_date.date() if hasattr(ppr_date, "date") else date(2025, 12, 18),
                fact_date=ppr_date.date() if hasattr(ppr_date, "date") else None,
                responsible=str(responsible) if responsible else None,
                status="done" if "исполнено" in str(status).lower() else "planned",
                work_types_done=["11.1", "11.2", "11.3", "11.4", "11.5", "11.6"],
            )
            db.add(plan)

    db.commit()
    print(f"✓ Импортировано объектов ВОЛС: {count}")


def seed_sample_plans(db: Session):
    """Создаём несколько плановых задач на октябрь 2026 для демонстрации"""
    objects = db.query(Object).filter(Object.object_type == "camera_integration").limit(15).all()
    if not objects:
        return

    templates = {t.code: t for t in db.query(PPRTemplate).all()}
    base_date = date(2026, 10, 15)

    for i, obj in enumerate(objects):
        planned = base_date + timedelta(days=i % 10)
        plan = PPRPlan(
            object_id=obj.id,
            template_id=templates.get("7.5").id if "7.5" in templates else None,
            title=f"ППР {obj.code} — октябрь 2026",
            planned_date=planned,
            responsible=obj.responsible_default or "Инженер ОСС",
            status="planned",
            work_types_done=[],
        )
        db.add(plan)
    db.commit()
    print(f"✓ Создано плановых задач на октябрь: {len(objects)}")


def run_seed():
    create_tables()
    db = SessionLocal()
    try:
        seed_templates(db)
        seed_users(db)
        import_integration_objects(db)
        import_voles_objects(db)
        seed_sample_plans(db)
        print("\n✅ База данных инициализирована успешно")
    finally:
        db.close()


if __name__ == "__main__":
    run_seed()
