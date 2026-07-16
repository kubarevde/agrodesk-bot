import json

import gspread
from google.oauth2.service_account import Credentials

from app.config import settings

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class SheetsClient:
    def __init__(self, client: gspread.Client):
        self._client = client
        self._spreadsheet = client.open(settings.google_sheets_name)

    @classmethod
    def from_service_account(cls) -> "SheetsClient":
        if settings.google_creds_json:
            creds_dict = json.loads(settings.google_creds_json)
            creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        else:
            creds = Credentials.from_service_account_file(
                settings.google_creds_path,
                scopes=SCOPES,
            )

        client = gspread.authorize(creds)
        return cls(client)

    def work_log_sheet(self):
        return self._spreadsheet.worksheet("work_log")

    def append_work_log_row(self, row: list) -> None:
        self.work_log_sheet().append_row(row, value_input_option="RAW")

    def get_open_shift_row_index(self, telegram_id: int):
        values = self.work_log_sheet().get_all_values()
        if not values:
            return None

        headers = values[0]
        try:
            telegram_id_idx = headers.index("telegram_id")
            status_idx = headers.index("status")
        except ValueError:
            return None

        for i, row in enumerate(values[1:], start=2):
            tg = row[telegram_id_idx] if len(row) > telegram_id_idx else ""
            st = row[status_idx] if len(row) > status_idx else ""
            if str(tg).strip() == str(telegram_id) and str(st).strip().lower() == "open":
                return i
        return None

    def close_shift(
        self,
        row_index: int,
        end_time: str,
        description: str,
        comment: str,
        duration_raw: int,
        duration_rounded: float,
    ) -> None:
        sheet = self.work_log_sheet()
        sheet.update_cell(row_index, 7, end_time)
        sheet.update_cell(row_index, 11, description)
        sheet.update_cell(row_index, 12, comment)
        sheet.update_cell(row_index, 13, "closed")
        sheet.update_cell(row_index, 14, duration_raw)
        sheet.update_cell(row_index, 15, duration_rounded)
