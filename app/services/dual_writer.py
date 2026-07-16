"""Write shifts to PostgreSQL (ApiClient) with optional Google Sheets mirror."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date
from typing import TYPE_CHECKING, Any

from app.config import settings

if TYPE_CHECKING:
    from app.services.api_client import ApiClient
    from app.services.sheets import SheetsClient

logger = logging.getLogger(__name__)


class DualWriter:
    """Primary path: PostgreSQL via ApiClient. Mirror: Google Sheets (never blocks)."""

    def __init__(self, api: ApiClient, sheets: SheetsClient | None) -> None:
        self.api = api
        self.sheets = sheets
        self.enabled = settings.sheets_mirror_enabled and sheets is not None

    async def open_shift(
        self,
        tg_id: int,
        location_id: str,
        location_name: str,
        work_type_id: str,
        work_type_name: str,
        equipment_id: str | None,
        equipment_name: str | None,
        lat: float | None,
        lng: float | None,
        employee: dict[str, Any],
        start_time_str: str,
    ) -> dict | None:
        result = await self.api.open_shift(
            tg_id,
            location_id,
            work_type_id,
            equipment_id,
            lat,
            lng,
        )
        if result is None:
            return None

        if self.enabled and self.sheets is not None:
            try:
                row = [
                    str(uuid.uuid4())[:8],
                    date.today().isoformat(),
                    employee.get('employee_code', ''),
                    employee.get('full_name') or employee.get('employee_name', ''),
                    str(tg_id),
                    start_time_str,
                    '',
                    work_type_name,
                    location_name,
                    equipment_name or '',
                    '',
                    '',
                    'open',
                    '',
                    '',
                    str(lat) if lat else '',
                    str(lng) if lng else '',
                ]
                await asyncio.to_thread(self.sheets.append_work_log_row, row)
            except Exception as e:
                logger.warning('[SheetsMirror] open_shift failed: %s', e)

        return result

    async def close_shift(
        self,
        tg_id: int,
        description: str,
        employee: dict[str, Any],
        end_time_str: str,
    ) -> dict | None:
        result = await self.api.close_shift(tg_id, description)
        if result is None:
            return None

        if self.enabled and self.sheets is not None:
            try:
                row_index = await asyncio.to_thread(
                    self.sheets.get_open_shift_row_index,
                    tg_id,
                )
                if row_index:
                    await asyncio.to_thread(
                        self.sheets.close_shift,
                        row_index=row_index,
                        end_time=end_time_str,
                        description=description,
                        comment='',
                        duration_raw=int(result.get('duration_raw', 0)),
                        duration_rounded=float(result.get('duration_rounded', 0)),
                    )
            except Exception as e:
                logger.warning('[SheetsMirror] close_shift failed: %s', e)

        return result

    async def open_shift_for_employee(
        self,
        admin_tg_id: int,
        employee_id: str,
        employee: dict[str, Any],
        location_id: str,
        location_name: str,
        work_type_id: str,
        work_type_name: str,
        equipment_id: str | None,
        equipment_name: str | None,
        start_time: str,
        end_time: str,
        description: str,
    ) -> dict | None:
        result = await self.api.open_shift_for_employee(
            admin_tg_id,
            employee_id,
            location_id,
            work_type_id,
            equipment_id,
            start_time,
            end_time,
            description,
        )
        if result is None:
            return None

        if self.enabled and self.sheets is not None:
            try:
                row = [
                    str(uuid.uuid4())[:8],
                    start_time[:10],
                    employee.get('employee_code', ''),
                    employee.get('full_name') or employee.get('employee_name', ''),
                    str(employee.get('telegram_id', '')),
                    start_time,
                    end_time,
                    work_type_name,
                    location_name,
                    equipment_name or '',
                    description,
                    '',
                    'closed',
                    '',
                    '',
                    '',
                    '',
                ]
                await asyncio.to_thread(self.sheets.append_work_log_row, row)
            except Exception as e:
                logger.warning('[SheetsMirror] open_shift_for_employee failed: %s', e)

        return result

    async def close_shift_for_employee(
        self,
        admin_tg_id: int,
        shift_id: str,
        description: str,
        employee: dict[str, Any],
        end_time_str: str,
    ) -> dict | None:
        result = await self.api.close_shift_for_employee(admin_tg_id, shift_id, description)
        if result is None:
            return None

        if self.enabled and self.sheets is not None:
            try:
                employee_tg = employee.get('telegram_id')
                tg_for_lookup = int(employee_tg) if employee_tg else None
                row_index = None
                if tg_for_lookup:
                    row_index = await asyncio.to_thread(
                        self.sheets.get_open_shift_row_index,
                        tg_for_lookup,
                    )
                if row_index:
                    await asyncio.to_thread(
                        self.sheets.close_shift,
                        row_index=row_index,
                        end_time=end_time_str,
                        description=description,
                        comment='',
                        duration_raw=int(result.get('duration_raw', 0)),
                        duration_rounded=float(result.get('duration_rounded', 0)),
                    )
            except Exception as e:
                logger.warning('[SheetsMirror] close_shift_for_employee failed: %s', e)

        return result
