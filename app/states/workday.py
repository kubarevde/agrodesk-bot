from aiogram.fsm.state import State, StatesGroup


class StartWork(StatesGroup):
    location = State()
    geo = State()
    work_type = State()
    equipment = State()
    comment = State()


class EndWork(StatesGroup):
    description = State()
    comment = State()


class AdminAddShift(StatesGroup):
    employee_select = State()
    start_date = State()
    start_time = State()
    end_date = State()
    end_time = State()
    location = State()
    work_type = State()
    equipment = State()
    description = State()
    comment = State()


class AdminCloseShift(StatesGroup):
    employee_select = State()
    end_date = State()
    end_time = State()
    description = State()
    comment = State()


class AdminBroadcast(StatesGroup):
    target_select = State()
    message_text = State()
