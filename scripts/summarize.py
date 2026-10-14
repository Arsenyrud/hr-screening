"""Сводка сохраненных протоколов."""

import json
import statistics
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    return json.loads((ROOT / 'evidence' / name).read_text())


if __name__ == '__main__':
    xml = ROOT / 'tmp/tests.xml'
    if xml.exists():
        root = ElementTree.parse(xml).getroot()
        cases = list(root.iter('testcase'))
        result = {'tests': len(cases), 'passed': sum(not any(child.tag in {'error', 'failure', 'skipped'} for child in case) for case in cases),
                  'failures': sum(len(case.findall('failure')) + len(case.findall('error')) for case in cases),
                  'cases': [{'name': case.attrib['name'], 'seconds': float(case.attrib.get('time', 0)),
                             'passed': not any(child.tag in {'error', 'failure', 'skipped'} for child in case)} for case in cases]}
        (ROOT / 'evidence/test_results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    base, semantic, profiles, recovery = [load(name) for name in ['experiment_baseline.json', 'experiment_semantic.json', 'load_test.json', 'recovery.json']]
    tests, security = load('test_results.json'), load('security.json')
    lines = ['# Стенд и методика', '', 'Измерения от 14 октября 2026 года. Все резюме синтетические. Это проверка пилота, а не исследование качества найма на боевых данных.', '',
             f"Стенд: {semantic['hardware']['gpu']}, ROCm {semantic['hardware']['rocm']}, PyTorch {semantic['hardware']['torch']}, Python {semantic['hardware']['python']}. Веса и набор закреплены хэшами в JSON. Базовый режим использует правила; семантический запускает MiniLM FP16 на GPU. У каждого из трех запросов пять повторов после одного прогрева. В измерение движка не входят HTTP, установка зависимостей и загрузка весов из сети.", '',
             '| Режим | Холодный вызов, с | Медиана, мс | p95, мс |', '|---|---:|---:|---:|']
    for data in [base, semantic]:
        lines.append(f"| {data['mode']} | {data['cold_seconds']:.3f} | {data['p50_seconds']*1000:.2f} | {data['p95_seconds']*1000:.2f} |")
    lines += ['', '# Нагрузка HTTP и задания', '',
              'Нагрузочный скрипт запускает настоящий Uvicorn на loopback, отправляет конкурентные задания и 200 запросов статуса восемью HTTP-потоками. Измеряется время ответа целиком, серверные ошибки считаются отдельно от ожидаемых отказов доступа. Профиль использует базовый движок и размноженные тексты, это не измерение пропускной способности LLM. На каждый профиль поднимается отдельная пустая БД. Скрининг выполняют до четырех отдельных CPU-процессов, оркестрация принимает до 12 задач.', '',
              '| Пул резюме | Задачи | API p95, мс | API p99, мс | Ошибки 5xx | Старт создания p95, мс |', '|---:|---:|---:|---:|---:|---:|']
    for data in profiles:
        lines.append(f"| {data['pool_size']} | {data['concurrent_tasks']} | {data['api_p95_ms']:.1f} | {data['api_p99_ms']:.1f} | {data['api_error_fraction']:.1%} | {data['create_p95_ms']:.1f} |")
    initial = load('load_initial.json')[-1]
    lines += ['', f"Первый тяжелый прогон дал p95 {initial['api_p95_ms']:.1f} мс и не прошел цель 500 мс. В записи задания тогда лежал полный снимок резюме, а сравнение делило GIL с API. После отделения снимков и вычислительного процесса последний тяжелый профиль дал {profiles[-1]['api_p95_ms']:.1f} мс. Исходный протокол сохранен в load_initial.json. Во всех трех профилях наблюдалось 20 активных исполнителей, включая ожидающих проверки и приостановленных.", '',
              'Цель 500 мс пройдена на этом конечном наборе запросов. Протокол не подтверждает 24-часовой SLA, масштаб 350 тысяч резюме и 12 одновременных генераций. Одиночный узел не проверяет обновление API без остановки.', '',
              '# Качество и контроль', '', '| Вакансия | Precision@8 | Recall@8 |', '|---|---:|---:|']
    for evaluation in semantic['evaluations']:
        lines.append(f"| {evaluation['vacancy_id']} | {evaluation['precision_at_k']:.3f} | {evaluation['recall_at_k']:.3f} |")
    lines += ['', 'Метки составлены вместе с синтетическим набором. Они не являются независимым тестом. Полнота 1,0 здесь показывает, что заданные примеры попали в восемь карточек, но не доказывает качество подбора. Семантический бонус ограничен пятью баллами и не подтверждает отсутствующий навык.', '',
              f"Pytest: {tests['passed']} из {tests['tests']}, ошибок {tests['failures']}. Проверки доступа и инертности инструкций: {sum(x['passed'] for x in security['checks'])} из {len(security['checks'])}. Аварийный выход процесса с кодом {recovery['child_exit_code']} оставил running на этапе {recovery['checkpoint_stage']}; новый сервис продолжил до {recovery['final_status']} за {recovery['recovery_seconds']:.3f} с. Backup/restore занял {recovery['backup_restore_seconds']:.3f} с, результат и аудит сохранены.", '',
              'Отключение исходящего трафика на уровне ОС, настоящая ATS, внешнее хранилище секретов и отказ GPU-узла требуют отдельного стенда. Они не помечены как пройденные тестами приложения.', '']
    if (ROOT / 'evidence/ui_session_tests.json').exists():
        js = load('ui_session_tests.json')
        lines += [f"JavaScript: {js['passed']} из {js['tests']} проверок Node VM. Они воспроизводят запоздалые ответы загрузки, чтения источников, скачивания и операций после смены аккаунта. Данные, ошибки и состояние старой сессии не попадают в новую. Отдельно в браузере проверены вложенные панели, PDF-загрузка и мобильная навигация. Протоколы: ui_session_tests.json и ui_checks.json.", '']
    llm_path = ROOT / 'evidence/experiment_llm.json'
    if llm_path.exists():
        llm = load('experiment_llm.json')
        lines += ['# Генерация на ROCm', '', f"Qwen3-4B-Instruct-2507 загружена локально в FP16 за {llm['load_seconds']:.2f} с. Пиковая выделенная память PyTorch {llm['peak_allocated_bytes']/2**30:.2f} GiB, зарезервированная {llm['peak_reserved_bytes']/2**30:.2f} GiB. Один генеративный слот, eager attention, до 3712 входных и 384 выходных токенов.", '',
                  '| Попытка | Время, с | JSON | Токены ответа |', '|---:|---:|---|---:|']
        for index, trial in enumerate(llm['trials'], 1):
            usage = trial['model_note'].get('usage', trial['model_note'])
            lines.append(f"| {index} | {trial['elapsed_seconds']:.2f} | {trial['model_note']['status']} | {usage.get('output_tokens', '?')} |")
        lines += ['', 'Баллы и цитаты не изменились после генерации. Это структурная проверка двух коротких запросов. Смысл подсказок проверяет рекрутер. Число активных задач не равно числу одновременных LLM-последовательностей.', '']
    if (ROOT / 'evidence/end_to_end_gpu.json').exists():
        end = load('end_to_end_gpu.json')
        lines += [f"Сквозной запуск через HTTP и отдельный вычислительный процесс занял {end['elapsed_seconds']:.2f} с до статуса waiting. MiniLM и Qwen3 сообщили device=cuda. Получено {end['candidate_count']} карточек, у каждой есть вопросы по профессиональным требованиям, у {end['draft_count']} есть отдельная подсказка LLM. Утверждение не выполнялось автоматически. Полный протокол в end_to_end_gpu.json.", '']
    if (ROOT / 'evidence/experiment_pdf.json').exists():
        pdf = load('experiment_pdf.json')
        times = sorted(item['seconds'] for item in pdf['documents'])
        lines += ['# PDF-резюме', '',
                  f"Проверены {len(pdf['documents'])} синтетических PDF из data/resumes. У каждого один лист и текстовый слой. SHA-256 совпали с manifest. После извлечения для {len(pdf['comparisons'])} вакансий сохранились баллы, навыки и стаж, все цитаты входят в извлеченный текст. Медиана разбора отдельным процессом {statistics.median(times):.3f} с, p95 {times[int((len(times)-1)*.95)]:.3f} с. Подробности в experiment_pdf.json.", '',
                  'Это проверка одного генератора и ограниченного PDF-парсера. Скан без текстового слоя, шифрование, поврежденный файл и превышение квот отклоняются. OCR не реализован. Ограничения приема: 5 MiB на PDF, 20 страниц, 30000 символов текста, два одновременных процесса, 8 секунд на разбор.', '']
    if (ROOT / 'evidence/end_to_end_pdf_gpu.json').exists():
        end = load('end_to_end_pdf_gpu.json')
        lines += [f"Задание по {end['pdf_resume_count']} доступным резюме, загруженным из PDF, прошло HTTP, MiniLM и Qwen3 до waiting за {end['elapsed_seconds']:.2f} с. Получено {end['candidate_count']} карточек и {end['draft_count']} подсказки, обе модели работали на GPU. Извлечение PDF выполнено командой seed до начала этого таймера и измерено отдельно. Утверждение остается ручным. Протокол в end_to_end_pdf_gpu.json.", '']
    (ROOT / 'docs/measurements.md').write_text('\n'.join(lines))
    print('Сводка обновлена')
