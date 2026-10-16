import sys
import unittest
from datetime import date
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import Department, DailyCheck, Object, PPRPlan, PPRTemplate
from planning import _planned_dates_for_period, generate_plans_for_period
from report_service import export_ppr_period_report


class PPRCoverageTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_daily_periodicity_returns_every_day_of_month(self):
        dates = _planned_dates_for_period(2026, 10, "daily")
        self.assertEqual(len(dates), 31)
        self.assertEqual(dates[0], date(2026, 10, 1))
        self.assertEqual(dates[-1], date(2026, 10, 31))

    def test_daily_template_creates_per_object_per_day_without_duplicates(self):
        department = Department(name="ОСС", is_active=True, duty_enabled=True)
        self.db.add(department)
        obj = Object(code="COD-01", name="ЦОД", object_type="cod", status="active")
        template = PPRTemplate(
            code="DC-1", name="Ежедневный контроль ЦОД",
            object_types=["cod"], work_items=["Температура и климат"],
            periodicity="daily", work_direction="sysadmin", is_active=True,
            department_ids=[], excluded_department_ids=[],
        )
        self.db.add_all([obj, template])
        self.db.commit()

        first = generate_plans_for_period(
            self.db, 2026, 10, only_without_plan=True,
            prefer_duty=False, include_daily_templates=True,
            department_id=department.id,
        )
        self.assertEqual(first["created"], 31)
        self.assertEqual(self.db.query(PPRPlan).filter_by(object_id=obj.id).count(), 31)

        second = generate_plans_for_period(
            self.db, 2026, 10, only_without_plan=True,
            prefer_duty=False, include_daily_templates=True,
            department_id=department.id,
        )
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["skipped"], 31)

    def test_report_contains_all_objects_and_daily_checks(self):
        self.db.add_all([
            Object(code="INT-01", name="Камера", object_type="camera_integration", status="active"),
            Object(code="COD-01", name="Дата-центр", object_type="cod", status="active"),
            Object(code="OLD-01", name="Старый объект", object_type="other", status="decommissioned"),
        ])
        self.db.add(DailyCheck(
            check_date=date(2026, 10, 15), engineer="Инженер",
            monitoring_dashboard="ok", critical_services="ok",
            logs_security="ok", config_backups="ok", channel_utilization="ok",
            ups_status="ok", incidents_logged=True, checklist=[],
        ))
        self.db.commit()

        data = export_ppr_period_report(self.db, date(2026, 10, 1), date(2026, 10, 31))
        workbook = load_workbook(BytesIO(data), read_only=True)
        self.assertIn("Все объекты", workbook.sheetnames)
        self.assertIn("Ежедневный контроль", workbook.sheetnames)
        registry = workbook["Все объекты"]
        codes = {registry.cell(row=row, column=2).value for row in range(4, registry.max_row + 1)}
        self.assertEqual(codes, {"INT-01", "COD-01", "OLD-01"})
        self.assertEqual(workbook["Ежедневный контроль"].max_row, 4)
        workbook.close()


    def test_us_address_entities_are_counted_by_type(self):
        us = Object(code="US-01", name="Узел связи", object_type="us", status="active")
        self.db.add(us)
        self.db.commit()
        addresses = []
        for prefix, object_type, count in (("OVN", "ovn", 27), ("INT", "camera_integration", 1), ("LU", "lu", 4), ("P", "p", 4)):
            for index in range(1, count + 1):
                addresses.append(Object(
                    code=f"{prefix}-{index:03d}",
                    name=f"{prefix} address {index}",
                    object_type=object_type,
                    status="active",
                    parent_us_id=us.id,
                ))
        self.db.add_all(addresses)
        self.db.commit()

        rows = self.db.query(Object.object_type, __import__("sqlalchemy").func.count(Object.id)).filter(
            Object.parent_us_id == us.id,
            Object.status != "decommissioned",
        ).group_by(Object.object_type).all()
        counts = dict(rows)
        self.assertEqual(sum(counts.values()), 36)
        self.assertEqual(counts, {"ovn": 27, "camera_integration": 1, "lu": 4, "p": 4})

if __name__ == "__main__":
    unittest.main()
