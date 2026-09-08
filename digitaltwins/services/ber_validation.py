_BER_CONTROL_MODES = {'amp', 'watt'}
_BER_REGEN_MODES = {'instant', 'next'}
_BER_SETPOINT_RANGES = {'amp': (7.5, 145), 'watt': (500, 14000)}
_BER_MAX_DURATION_SECONDS = 28_800  # 8 hours


def validate_ber_experiment(body):
    if not isinstance(body, list) or not body:
        return None, 'Experiment JSON must be a non-empty array of command objects.'

    control_mode = None
    control_mode_set = False
    regen_mode_set = False
    last_time = None
    cleaned = []

    for i, item in enumerate(body):
        if not isinstance(item, dict) or set(item) != {'time', 'command', 'value'}:
            return None, f'Command at index {i} must be an object with time, command and value.'

        time = item.get('time')
        if not isinstance(time, (int, float)) or isinstance(time, bool) or time < 0:
            return None, f'Command at index {i} has an invalid time value.'
        if last_time is not None and time <= last_time:
            return None, 'Command times must be strictly increasing.'
        last_time = time

        command = item.get('command')
        value = item.get('value')

        if command == 'set_control_mode':
            if not isinstance(value, str) or value not in _BER_CONTROL_MODES:
                return None, f'Invalid control mode "{value}" at index {i}.'
            control_mode = value
            control_mode_set = True
        elif command == 'set_regen_mode':
            if not isinstance(value, str) or value not in _BER_REGEN_MODES:
                return None, f'Invalid regeneration mode "{value}" at index {i}.'
            regen_mode_set = True
        elif command == 'change_setpoint':
            if control_mode is None:
                return None, f'"change_setpoint" at index {i} requires a control mode to be set first.'
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                return None, f'Setpoint at index {i} must be numeric.'
            lo, hi = _BER_SETPOINT_RANGES[control_mode]
            if not (lo <= numeric_value <= hi):
                return None, f'Setpoint {numeric_value} at index {i} is out of range for {control_mode} mode ({lo}-{hi}).'
        else:
            return None, f'Unknown command "{command}" at index {i}.'

        cleaned.append({'time': time, 'command': command, 'value': value})

    if not control_mode_set or not regen_mode_set:
        return None, 'The experiment must set both a control mode and a regeneration mode.'

    if last_time > _BER_MAX_DURATION_SECONDS:
        return None, f'Total experiment duration must not exceed {_BER_MAX_DURATION_SECONDS} seconds (8 hours).'

    return cleaned, None
