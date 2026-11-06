/* The CEA DT Scenario Simulation page's scenario builder: the table of
time-series signals and the scalar parameters, loading a scenario from a JSON
file, and building the JSON that is run. The variables, with their units and
ranges, come from CEA_VARIABLES (digitaltwins/pages.py) in the page's
#cea-variables element. Running is not wired yet: the CEA API does not exist. */
(function () {
    'use strict';

    var VARIABLES = JSON.parse(document.getElementById('cea-variables').textContent);
    var SIGNALS = VARIABLES.filter(function (v) { return v.kind === 'signal'; });
    var SCALARS = VARIABLES.filter(function (v) { return v.kind === 'scalar'; });
    // Above this many time steps the table is not drawn: thousands of inputs would
    // freeze the page. A longer scenario can still be uploaded and run as it is.
    var MAX_TABLE_ROWS = 500;
    var MAX_FILE_BYTES = 10 * 1024 * 1024;

    // The scenario as typed: one array of cell texts per time step (in SIGNALS
    // order) and the scalar texts by name. Numbers are parsed only when checked
    // or sent, so a half-typed value is kept as the user left it.
    var state = { rows: [emptyRow()], scalars: {}, large: false };
    // Problems are marked only from the first press of Run on, so the user is not
    // greeted by a table of red cells they have not had the chance to fill in.
    var showErrors = false;

    var tbody = document.getElementById('signals-body');
    var signalsWrapper = document.getElementById('signals-wrapper');
    var largeNotice = document.getElementById('large-scenario-notice');
    var scalarInputs = document.querySelectorAll('[data-scalar]');
    var tablePanel = document.getElementById('table-panel');
    var uploadPanel = document.getElementById('upload-panel');
    var uploadFeedback = document.getElementById('upload-feedback');
    var errorsBox = document.getElementById('scenario-errors');
    var errorsList = document.getElementById('scenario-errors-list');
    var statusText = document.getElementById('scenario-status');
    var runBtn = document.getElementById('run-simulation-btn');
    var runFeedback = document.getElementById('run-feedback');
    var tableFeedback = document.getElementById('table-feedback');

    // Each variable's description, as in the documentation, on hover over its name.
    document.querySelectorAll('#scenario-builder [data-bs-toggle="popover"]').forEach(function (el) {
        bootstrap.Popover.getOrCreateInstance(el);
    });

    function emptyRow() {
        return SIGNALS.map(function () { return ''; });
    }

    // A comma followed by groups of exactly three digits, as in 3,600: an English
    // spreadsheet's thousands separator, or a Greek one's 3.600.
    function isAmbiguousComma(text) {
        return /^[-+]?[1-9]\d{0,2}(,\d{3})+$/.test(String(text).trim());
    }

    function inRange(variable, value) {
        return value >= variable.min && (variable.max === null || value <= variable.max);
    }

    // The readings of an ambiguous comma that the variable's range allows: 1,291 is
    // a cell voltage of 1.291 V, never 1291 V, but a timeStamp of 3,600 could be
    // either 3600 s or 3.6 s. A wrong guess would be a thousand times off.
    function commaReadings(variable, text) {
        var s = String(text).trim();
        var readings = [Number(s.replace(/,/g, ''))];
        if (s.split(',').length === 2) readings.push(Number(s.replace(',', '.')));
        return readings.filter(function (value) { return inRange(variable, value); });
    }

    // Null for an empty cell, NaN for text that is not a number (or not a single one).
    function parseNumber(text) {
        var s = String(text).trim();
        if (s === '') return null;
        if (isAmbiguousComma(s)) return NaN;
        // Spreadsheets in a Greek (or other European) locale copy 1,29 for 1.29.
        if (/^[-+]?\d*,\d+$/.test(s)) s = s.replace(',', '.');
        if (!/^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i.test(s)) return NaN;
        return Number(s);
    }

    // The cell's value for this variable; an ambiguous comma is settled by its range.
    function readValue(variable, text) {
        if (!isAmbiguousComma(text)) return parseNumber(text);
        var readings = commaReadings(variable, text);
        return readings.length === 1 ? readings[0] : NaN;
    }

    function valueError(variable, text) {
        if (isAmbiguousComma(text)) {
            var readings = commaReadings(variable, text);
            if (readings.length > 1) return 'unclear comma, write it with a dot for decimals and no thousands separator';
            if (!readings.length) return 'outside ' + variable.range;
            return '';
        }
        var value = parseNumber(text);
        if (value === null) return 'missing';
        if (isNaN(value)) return 'not a number';
        if (value < variable.min || (variable.max !== null && value > variable.max)) return 'outside ' + variable.range;
        return '';
    }

    // Problems keyed by 'row:col' for cells and by name for scalars, in table order.
    function validate() {
        var cells = {}, scalars = {}, messages = [];
        state.rows.forEach(function (row, r) {
            SIGNALS.forEach(function (variable, c) {
                var error = valueError(variable, row[c]);
                if (!error && c === 0 && r > 0) {
                    var previous = readValue(variable, state.rows[r - 1][0]);
                    if (typeof previous === 'number' && !isNaN(previous) && readValue(variable, row[0]) <= previous) {
                        error = 'must be later than the previous time step';
                    }
                }
                if (error) {
                    cells[r + ':' + c] = error;
                    messages.push('Time step ' + (r + 1) + ', ' + variable.label + ': ' + error);
                }
            });
        });
        SCALARS.forEach(function (variable) {
            var error = valueError(variable, state.scalars[variable.name] || '');
            if (error) {
                scalars[variable.name] = error;
                messages.push(variable.label + ': ' + error);
            }
        });
        return { cells: cells, scalars: scalars, messages: messages };
    }

    // ---- Table ----

    function buildRow(row, r) {
        var tr = document.createElement('tr');
        var number = document.createElement('td');
        number.className = 'text-center text-body-tertiary ps-3';
        number.textContent = r + 1;
        tr.appendChild(number);

        SIGNALS.forEach(function (variable, c) {
            var td = document.createElement('td');
            td.className = 'p-1';
            var input = document.createElement('input');
            input.type = 'text';
            input.inputMode = 'decimal';
            input.size = 1;
            input.autocomplete = 'off';
            input.className = 'form-control text-end font-monospace';
            input.value = row[c];
            input.dataset.row = r;
            input.dataset.col = c;
            input.setAttribute('aria-label', variable.label + ', time step ' + (r + 1));
            td.appendChild(input);
            tr.appendChild(td);
        });

        var remove = document.createElement('td');
        var button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn btn-link btn-sm text-body-tertiary px-2';
        button.dataset.removeRow = r;
        button.setAttribute('aria-label', 'Remove time step ' + (r + 1));
        button.innerHTML = '<span class="fas fa-xmark"></span>';
        remove.appendChild(button);
        tr.appendChild(remove);
        return tr;
    }

    function renderTable() {
        tbody.replaceChildren();
        largeNotice.hidden = !state.large;
        signalsWrapper.hidden = state.large;
        if (state.large) {
            document.getElementById('large-scenario-steps').textContent = state.rows.length;
        } else {
            var fragment = document.createDocumentFragment();
            state.rows.forEach(function (row, r) { fragment.appendChild(buildRow(row, r)); });
            tbody.appendChild(fragment);
        }
        scalarInputs.forEach(function (input) { input.value = state.scalars[input.dataset.scalar] || ''; });
        refresh();
    }

    // Re-checks the scenario and updates the marks, status and Run button
    // without redrawing the table, so the focused cell keeps its caret.
    function refresh() {
        var result = validate();

        tbody.querySelectorAll('input').forEach(function (input) {
            var error = showErrors && result.cells[input.dataset.row + ':' + input.dataset.col];
            input.classList.toggle('is-invalid', !!error);
            input.title = error || '';
        });
        scalarInputs.forEach(function (input) {
            var error = showErrors && result.scalars[input.dataset.scalar];
            input.classList.toggle('is-invalid', !!error);
            input.nextElementSibling.textContent = error ? 'Value ' + error + '.' : '';
        });

        // An untouched table is not a list of mistakes yet.
        var blank = isBlank();

        errorsList.replaceChildren();
        result.messages.slice(0, 5).forEach(function (message) {
            var li = document.createElement('li');
            li.textContent = message;
            errorsList.appendChild(li);
        });
        if (result.messages.length > 5) {
            var more = document.createElement('li');
            more.textContent = 'and ' + (result.messages.length - 5) + ' more';
            errorsList.appendChild(more);
        }
        errorsBox.hidden = !showErrors || result.messages.length === 0;

        var valueCount = state.rows.length * SIGNALS.length + SCALARS.length;
        if (blank) {
            statusText.textContent = 'Fill in the table, or load the example to see how a scenario looks.';
        } else {
            statusText.textContent = result.messages.length
                ? result.messages.length + ' of ' + valueCount + ' values still need attention.'
                : state.rows.length + ' time steps · ' + valueCount + ' values ready.';
        }
        runFeedback.replaceChildren();
        tableFeedback.replaceChildren();
        return result;
    }

    function isBlank() {
        return state.rows.every(function (row) { return row.every(function (v) { return String(v).trim() === ''; }); })
            && SCALARS.every(function (v) { return !String(state.scalars[v.name] || '').trim(); });
    }

    function focusCell(r, c) {
        var input = tbody.querySelector('input[data-row="' + r + '"][data-col="' + c + '"]');
        if (input) { input.focus(); input.select(); }
    }

    tbody.addEventListener('input', function (e) {
        var input = e.target;
        state.rows[+input.dataset.row][+input.dataset.col] = input.value;
        refresh();
    });

    tbody.addEventListener('keydown', function (e) {
        var input = e.target;
        if (input.dataset.row === undefined) return;
        var r = +input.dataset.row, c = +input.dataset.col;
        if (e.key === 'Enter' || e.key === 'ArrowDown') {
            e.preventDefault();
            if (r + 1 >= state.rows.length && e.key === 'Enter') {
                addRow();
            }
            focusCell(r + 1, c);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            focusCell(r - 1, c);
        }
    });

    // A block copied from a spreadsheet arrives as tab-separated lines; it is
    // spread over the table from the cell it was pasted into.
    tbody.addEventListener('paste', function (e) {
        var input = e.target;
        if (input.dataset.row === undefined) return;
        var text = (e.clipboardData || window.clipboardData).getData('text');
        if (!/[\t\n]/.test(text.trim())) return;
        e.preventDefault();

        var lines = text.replace(/\r/g, '').replace(/\n+$/, '').split('\n');
        var r0 = +input.dataset.row, c0 = +input.dataset.col;
        if (r0 + lines.length > MAX_TABLE_ROWS) {
            showTableFull();
            return;
        }
        lines.forEach(function (line, i) {
            while (state.rows.length <= r0 + i) state.rows.push(emptyRow());
            line.split('\t').forEach(function (value, j) {
                if (c0 + j < SIGNALS.length) state.rows[r0 + i][c0 + j] = value.trim();
            });
        });
        renderTable();
        focusCell(r0, c0);
    });

    tbody.addEventListener('click', function (e) {
        var button = e.target.closest('[data-remove-row]');
        if (!button) return;
        state.rows.splice(+button.dataset.removeRow, 1);
        if (!state.rows.length) state.rows.push(emptyRow());
        renderTable();
    });

    scalarInputs.forEach(function (input) {
        input.addEventListener('input', function () {
            state.scalars[input.dataset.scalar] = input.value;
            refresh();
        });
    });

    function showTableFull() {
        showMessage(tableFeedback, 'warning', 'The table holds up to ' + MAX_TABLE_ROWS
            + ' time steps. Upload a longer scenario as a JSON file instead.');
    }

    function addRow() {
        if (state.rows.length >= MAX_TABLE_ROWS) {
            showTableFull();
            return;
        }
        state.rows.push(emptyRow());
        tbody.appendChild(buildRow(state.rows[state.rows.length - 1], state.rows.length - 1));
        refresh();
    }

    document.getElementById('add-row-btn').addEventListener('click', function () {
        addRow();
        focusCell(state.rows.length - 1, 0);
    });

    document.getElementById('fill-down-btn').addEventListener('click', function () {
        for (var r = 1; r < state.rows.length; r++) {
            for (var c = 1; c < SIGNALS.length; c++) {
                if (String(state.rows[r][c]).trim() === '') state.rows[r][c] = state.rows[r - 1][c];
            }
        }
        renderTable();
    });

    // ---- Confirmation ----

    var confirmModal = document.getElementById('scenario-confirm-modal');
    var confirmBtn = document.getElementById('scenario-confirm-btn');
    var onConfirm = null;

    // Runs options.onConfirm straight away on an empty scenario, and otherwise
    // only once the user confirms in the modal that their values may be lost.
    function confirmReplace(options) {
        if (isBlank()) {
            options.onConfirm();
            return;
        }
        document.getElementById('scenario-confirm-label').textContent = options.title;
        document.getElementById('scenario-confirm-message').textContent = options.message;
        confirmBtn.textContent = options.label;
        confirmBtn.className = 'btn ' + (options.danger ? 'btn-danger' : 'btn-primary');
        onConfirm = options.onConfirm;
        bootstrap.Modal.getOrCreateInstance(confirmModal).show();
    }

    confirmBtn.addEventListener('click', function () {
        var action = onConfirm;
        onConfirm = null;
        bootstrap.Modal.getOrCreateInstance(confirmModal).hide();
        if (action) action();
    });

    // Closing the modal any other way drops the pending action.
    confirmModal.addEventListener('hidden.bs.modal', function () { onConfirm = null; });

    document.getElementById('clear-btn').addEventListener('click', function () {
        confirmReplace({
            title: 'Clear the scenario',
            message: 'All time steps and scalar parameters you have entered will be removed.',
            label: 'Clear',
            danger: true,
            onConfirm: function () {
                state = { rows: [emptyRow()], scalars: {}, large: false };
                showErrors = false;
                uploadFeedback.replaceChildren();
                renderTable();
            },
        });
    });

    document.getElementById('load-example-btn').addEventListener('click', function () {
        confirmReplace({
            title: 'Load the example',
            message: 'The example scenario will replace the values you have entered.',
            label: 'Replace values',
            onConfirm: function () {
                loadScenario(JSON.parse(document.getElementById('example-json-source').textContent));
                renderTable();
            },
        });
    });

    // ---- JSON in and out ----

    // Loads a parsed scenario file into the state, or returns why it cannot.
    function loadScenario(data) {
        if (!data || typeof data !== 'object' || Array.isArray(data)) return 'The file must contain a JSON object.';
        var missing = VARIABLES.filter(function (v) { return !(v.name in data); })
            .map(function (v) { return v.name; });
        if (missing.length) return 'Missing variables: ' + missing.join(', ') + '.';
        if (!Array.isArray(data.timeStamp) || !data.timeStamp.length) return 'timeStamp must be a non-empty array.';
        var length = data.timeStamp.length;
        for (var i = 0; i < SIGNALS.length; i++) {
            var values = data[SIGNALS[i].name];
            if (!Array.isArray(values)) return SIGNALS[i].name + ' must be an array.';
            if (values.length !== length) {
                return SIGNALS[i].name + ' has ' + values.length + ' values but timeStamp has ' + length + '.';
            }
        }
        for (var j = 0; j < SCALARS.length; j++) {
            var value = data[SCALARS[j].name];
            if (value !== null && typeof value === 'object') return SCALARS[j].name + ' must be a single value.';
        }

        function text(value) { return value === null || value === undefined ? '' : String(value); }
        state = {
            rows: data.timeStamp.map(function (_, r) {
                return SIGNALS.map(function (v) { return text(data[v.name][r]); });
            }),
            scalars: {},
            large: length > MAX_TABLE_ROWS,
        };
        SCALARS.forEach(function (v) { state.scalars[v.name] = text(data[v.name]); });
        return '';
    }

    function buildScenario() {
        var scenario = {};
        SIGNALS.forEach(function (v, c) {
            scenario[v.name] = state.rows.map(function (row) { return readValue(v, row[c]); });
        });
        SCALARS.forEach(function (v) { scenario[v.name] = readValue(v, state.scalars[v.name] || ''); });
        return scenario;
    }

    // One variable per line, as in the example file, so the preview stays readable.
    function formatScenario(scenario) {
        return '{\n' + Object.keys(scenario).map(function (name) {
            return '    ' + JSON.stringify(name) + ': ' + JSON.stringify(scenario[name]).replace(/,/g, ', ');
        }).join(',\n') + '\n}';
    }

    function downloadJson(text, filename) {
        window.DT.triggerDownload(text, filename, 'application/json');
    }

    function showMessage(container, kind, text) {
        var alert = document.createElement('div');
        alert.className = 'alert alert-subtle-' + kind + ' fs-9 mt-3 mb-0';
        alert.textContent = text;
        container.replaceChildren(alert);
    }

    function setMode(mode) {
        tablePanel.hidden = mode !== 'table';
        uploadPanel.hidden = mode !== 'upload';
        document.getElementById('scenario-mode-' + mode).checked = true;
    }

    document.querySelectorAll('input[name="scenario-mode"]').forEach(function (radio) {
        radio.addEventListener('change', function () { setMode(radio.value); });
    });

    function readFile(file) {
        if (!file) return;
        if (file.size > MAX_FILE_BYTES) {
            showMessage(uploadFeedback, 'danger', file.name + ' is larger than 10 MB.');
            return;
        }
        confirmReplace({
            title: 'Replace with the uploaded file',
            message: 'The scenario in ' + file.name + ' will replace the values you have entered.',
            label: 'Replace values',
            onConfirm: function () { loadFile(file); },
        });
    }

    function loadFile(file) {
        file.text().then(function (text) {
            var data;
            try {
                data = JSON.parse(text);
            } catch (err) {
                showMessage(uploadFeedback, 'danger', file.name + ' is not valid JSON: ' + err.message);
                return;
            }
            var problem = loadScenario(data);
            if (problem) {
                showMessage(uploadFeedback, 'danger', file.name + ' could not be loaded. ' + problem);
                return;
            }
            renderTable();
            if (state.large) {
                showMessage(uploadFeedback, 'success', 'Loaded ' + file.name + ' with ' + state.rows.length
                    + ' time steps. It is too long to edit in the table and will be run as uploaded.');
            } else {
                showMessage(uploadFeedback, 'success', 'Loaded ' + file.name + ' into the table.');
                setMode('table');
            }
        }).catch(function (err) {
            console.error('Could not read the scenario file', err);
            showMessage(uploadFeedback, 'danger', file.name + ' could not be read. Choose the file again.');
        });
    }

    var jsonFileInput = document.getElementById('scenario-json-file');
    var jsonDropzone = document.getElementById('json-dropzone');

    jsonFileInput.addEventListener('change', function () {
        readFile(jsonFileInput.files && jsonFileInput.files[0]);
        // Choosing the same file again after editing it must load it again.
        jsonFileInput.value = '';
    });

    ['dragenter', 'dragover'].forEach(function (evt) {
        jsonDropzone.addEventListener(evt, function (e) {
            e.preventDefault();
            jsonDropzone.classList.add('border-primary');
        });
    });
    ['dragleave', 'drop'].forEach(function (evt) {
        jsonDropzone.addEventListener(evt, function (e) {
            e.preventDefault();
            jsonDropzone.classList.remove('border-primary');
        });
    });
    jsonDropzone.addEventListener('drop', function (e) {
        var files = e.dataTransfer && e.dataTransfer.files;
        if (files && files.length) readFile(files[0]);
    });

    document.getElementById('download-example-json').addEventListener('click', function (e) {
        e.preventDefault();
        downloadJson(document.getElementById('example-json-source').textContent, 'scenario-example.json');
    });

    document.getElementById('download-scenario-btn').addEventListener('click', function () {
        downloadJson(formatScenario(buildScenario()), 'cea-scenario.json');
    });

    document.getElementById('scenario-preview-modal').addEventListener('show.bs.modal', function () {
        document.getElementById('scenario-preview').textContent = formatScenario(buildScenario());
    });

    runBtn.addEventListener('click', function () {
        showErrors = true;
        if (refresh().messages.length) {
            // In upload mode the table is hidden, so the list is what can be shown.
            var first = (!tablePanel.hidden && document.querySelector('#scenario-builder .is-invalid')) || errorsBox;
            first.scrollIntoView({ behavior: 'smooth', block: 'center' });
            if (first !== errorsBox) first.focus({ preventScroll: true });
            return;
        }
        // TODO: POST buildScenario() to the backend once the CEA simulation API exists.
        showMessage(runFeedback, 'warning', 'Your scenario is valid, but runs cannot be started yet: the connection '
            + 'to the CEA simulation service is still being set up. You can download the scenario JSON in the meantime.');
    });

    renderTable();
}());
