# -*- coding: utf-8 -*-
"""
简历筛选系统 - 后端主程序
================================================
运行方式:
    python app.py
访问:
    http://本机IP:5000
================================================
"""
import os
import re
import hashlib
import logging
from datetime import date, datetime
from pathlib import Path
from contextlib import contextmanager

import pymysql
from pymysql.cursors import DictCursor
from flask import Flask, request, jsonify, render_template, send_file, abort
import pdfplumber


# ================================================================
# 【配置】
# ================================================================
class Config:
    # MySQL 连接
    DB_HOST     = '192.168.0.196'
    DB_PORT     = 3306
    DB_USER     = 'root'
    DB_PASSWORD = '123456'
    DB_NAME     = 'cx'

    # 简历根目录,按日期分子目录: D:\boss直聘\2026-04-23\xxx.pdf
    RESUME_ROOT = r'D:\boss直聘'

    # Flask 监听
    HOST = '0.0.0.0'          # 0.0.0.0 表示局域网其他机器也能访问
    PORT = 5000
    DEBUG = False


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
)
log = logging.getLogger(__name__)


# ================================================================
# 【数据库】连接池简化版,使用 contextmanager 包每次请求的连接
# ================================================================
def _new_conn():
    return pymysql.connect(
        host=Config.DB_HOST,
        port=Config.DB_PORT,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
        database=Config.DB_NAME,
        charset='utf8mb4',
        cursorclass=DictCursor,
        autocommit=False,
    )


@contextmanager
def db_cursor():
    """用法:with db_cursor() as cur: cur.execute(...)"""
    conn = _new_conn()
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ================================================================
# 【PDF 解析】
# ================================================================
def extract_pdf_text(pdf_path: str) -> str:
    """用 pdfplumber 抽全文文本。解析失败返回空串不抛异常。"""
    try:
        parts = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ''
                parts.append(t)
        return '\n'.join(parts)
    except Exception as e:
        log.warning(f'PDF 解析失败 {pdf_path}: {e}')
        return ''


def md5_of_file(path: str) -> str:
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


# ================================================================
# 【信息提取】从简历文本里抽姓名、性别、年龄、学历、技能、专业等
# ================================================================
SKILL_KEYWORDS = [
    'SPSS', 'R语言', 'SAS', 'Stata', 'MATLAB', 'Eviews',
    'Excel', 'Word', 'PowerPoint', 'PPT', 'WPS', 'Access',
    'SQL', 'MySQL', 'PostgreSQL', 'Oracle', 'SQLite',
    'Python', 'Pandas', 'Numpy', 'Scikit-learn', 'Matplotlib',
    'Tableau', 'Power BI', 'PowerBI', 'FineBI', '数据可视化',
    'Java', 'JavaScript', 'TypeScript', 'C++', 'C#', 'Go',
    'Rust', 'Ruby', 'PHP', 'Swift', 'Kotlin', 'Scala',
    'HTML', 'CSS', 'React', 'Vue', 'Angular', 'Node.js',
    'Django', 'Flask', 'Spring', 'SpringBoot', 'Spring Cloud',
    'MongoDB', 'Redis', 'Elasticsearch', 'Kafka', 'RabbitMQ',
    'Docker', 'Kubernetes', 'K8S', 'Jenkins', 'Git', 'Linux',
    'AWS', 'Azure', 'GCP', '阿里云', '腾讯云', '华为云',
    'TensorFlow', 'PyTorch', 'Keras', 'OpenCV',
    '机器学习', '深度学习', '神经网络', '自然语言处理', 'NLP',
    '计算机视觉', '人脸识别',
    'Photoshop', 'Illustrator', 'Figma', 'Axure', 'Sketch',
    'SAP', 'ERP', 'CRM', 'Scrum', 'Agile', '敏捷',
]


def extract_name(text: str):
    patterns = [
        r'(?:姓\s*名|name)\s*[:：]\s*([^\s\n\t，,。；;]{2,8})',
        r'^([^\s\n]{2,4})[\s\t]*(?:性别|专业|学历|出生|手机|电话|邮箱|Email)',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE | re.MULTILINE)
        if m:
            return m.group(1).strip()
    return None


def extract_gender(text: str):
    """
        提取性别,策略从严到宽:
        1. 先找"性别"附近的"男/女"(窗口 20 字符)——最可靠
        2. 明确英文 Male/Female
        3. 全文数 "男"/"女" 出现次数,多的胜出(处理 PDF 表格被打散的情况)
        """
    # 策略 1:性别关键词附近找(双向,20 字符内)
    # 匹配 "性别 男"、"性别：女"、"性别\n\n男"、"男 性别"(偶尔出现)等
    m = re.search(r'性\s*别[^\u4e00-\u9fa5A-Za-z0-9]{0,20}(男|女)', text)
    if m:
        return 'male' if m.group(1) == '男' else 'female'
    m = re.search(r'(男|女)[^\u4e00-\u9fa5A-Za-z0-9]{0,20}性\s*别', text)
    if m:
        return 'male' if m.group(1) == '男' else 'female'

    # 策略 2:英文
    if re.search(r'\bMale\b', text, re.IGNORECASE):
        return 'male'
    if re.search(r'\bFemale\b', text, re.IGNORECASE):
        return 'female'

    # 策略 3:按出现次数投票,排除常见干扰词
    # 先剔除干扰短语,再数单字
    cleaned = text
    for bad in ['男女不限', '不限男女', '男女', '子女', '女士', '男士',
                '男生', '女生', '男朋友', '女朋友', '男友', '女友',
                '男方', '女方', '父女', '母子', '母女', '父子']:
        cleaned = cleaned.replace(bad, '')
    male_count = cleaned.count('男')
    female_count = cleaned.count('女')
    if male_count > 0 and male_count > female_count:
        return 'male'
    if female_count > 0 and female_count > male_count:
        return 'female'

    return 'unknown'


def extract_age(text: str):
    # 直接写年龄
    for p in [
        r'年\s*龄\s*[:：]\s*(\d{1,2})\s*(?:岁)?',
        r'(\d{1,2})\s*岁',
        r'age\s*[:：]?\s*(\d{1,2})',
    ]:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            v = int(m.group(1))
            if 16 <= v <= 70:
                return v
    # 通过出生年份推算
    for p in [
        r'出生\s*(?:年月|日期|年份)\s*[:：]\s*((?:19|20)\d{2})',
        r'((?:19|20)\d{2})\s*年\s*(?:生|出生)',
        r'born\s+in\s+((?:19|20)\d{2})',
    ]:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            birth_year = int(m.group(1))
            age = datetime.now().year - birth_year
            if 16 <= age <= 70:
                return age
    return None


def extract_education(text: str):
    """返回最高学历 大专/本科/硕士/博士 或 None"""
    order = {'大专': 1, '本科': 2, '硕士': 3, '博士': 4}
    highest = None
    # 先看是否在文本中直接出现这些词
    for level in order:
        if level in text or (level == '硕士' and '研究生' in text):
            if not highest or order[level] > order[highest]:
                highest = level
    return highest


def extract_exp_years(text: str):
    for p in [
        r'工作\s*(?:经验|年限|经历)\s*[:：]\s*(\d+(?:\.\d+)?)\s*年',
        r'(\d+(?:\.\d+)?)\s*年\s*(?:工作经验|工作经历)',
        r'经验\s*[:：]\s*(\d+(?:\.\d+)?)\s*年',
    ]:
        m = re.search(p, text)
        if m:
            return float(m.group(1))
    # 工作时间段推算
    matches = re.findall(r'((?:20|19)\d{2})\s*[-—至~～]\s*(?:(?:20|19)\d{2}|至今|present)', text, re.IGNORECASE)
    if matches:
        earliest = min(int(y) for y in matches)
        exp = datetime.now().year - earliest
        if 0 <= exp <= 50:
            return float(exp)
    return None


def extract_majors(text: str):
    m = re.search(r'专\s*业\s*[:：]\s*([^\s\n，,。;；]{2,30})', text)
    if m:
        return [m.group(1).strip()]
    return []


def extract_skills(text: str):
    found = []
    for s in SKILL_KEYWORDS:
        pattern = re.escape(s)
        if re.search(pattern, text, re.IGNORECASE):
            found.append(s)
    # 去重保序
    seen = set()
    result = []
    for s in found:
        if s.lower() not in seen:
            seen.add(s.lower())
            result.append(s)
    return result


def extract_name_from_filename(file_name: str):
    """
    从 BOSS 直聘文件名切姓名:
    『【财务助理_杭州_5-6K】付亚慧_一年以内.pdf』 → 付亚慧
    规则:第一个 "】" 之后到第一个 "_" 之前
    """
    # 先去掉扩展名
    stem = os.path.splitext(file_name)[0]
    # 找 "】" 后的部分
    if '】' in stem:
        stem = stem.split('】', 1)[1]
    # 切第一个 _ 之前
    name = stem.split('_', 1)[0].strip()
    if 2 <= len(name) <= 10:
        return name
    return None

def parse_resume_file(pdf_path: str, file_name: str = None) -> dict:
    text = extract_pdf_text(pdf_path)
    # 姓名优先从文件名提取,兜底再从文本识别
    name = None
    if file_name:
        name = extract_name_from_filename(file_name)
    if not name:
        name = extract_name(text)
    return {
        'raw_text':       text,
        'auto_name':      name,
        'auto_gender':    extract_gender(text),
        'auto_age':       extract_age(text),
        'auto_education': extract_education(text),
        'auto_exp_years': extract_exp_years(text),
        'auto_majors':    ','.join(extract_majors(text)) or None,
        'auto_skills':    ','.join(extract_skills(text)) or None,
    }


# ================================================================
# 【扫描文件夹 + 入库】核心业务
# ================================================================
def scan_and_parse(target_date: date) -> int:
    """
    扫描某天的简历文件夹,对新增或内容变化的 PDF 进行解析并 upsert 入库。
    返回本次新解析的文件数。
    """
    folder = Path(Config.RESUME_ROOT) / target_date.strftime('%Y-%m-%d')
    if not folder.exists():
        log.info(f'文件夹不存在: {folder}')
        return 0

    pdf_files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == '.pdf']
    if not pdf_files:
        return 0

    # 先查库里已有的该日期记录,构建 {file_name: (id, file_hash)}
    with db_cursor() as cur:
        cur.execute(
            'SELECT id, file_name, file_hash FROM resume WHERE resume_date = %s',
            (target_date,)
        )
        existing = {row['file_name']: (row['id'], row['file_hash']) for row in cur.fetchall()}

    new_count = 0
    for pdf in pdf_files:
        file_name = pdf.name
        file_path = str(pdf.resolve())
        file_size = pdf.stat().st_size
        file_hash = md5_of_file(file_path)

        # 已存在且 hash 未变,跳过
        if file_name in existing and existing[file_name][1] == file_hash:
            continue

        log.info(f'解析: {file_name}')
        parsed = parse_resume_file(file_path,file_name)

        with db_cursor() as cur:
            # upsert:INSERT ... ON DUPLICATE KEY UPDATE,利用 (resume_date, file_name) 联合唯一键
            cur.execute(
                '''
                INSERT INTO resume
                    (resume_date, file_name, file_path, file_size, file_hash,
                     raw_text, auto_name, auto_gender, auto_age, auto_education,
                     auto_exp_years, auto_majors, auto_skills)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    file_path      = VALUES(file_path),
                    file_size      = VALUES(file_size),
                    file_hash      = VALUES(file_hash),
                    raw_text       = VALUES(raw_text),
                    auto_name      = VALUES(auto_name),
                    auto_gender    = VALUES(auto_gender),
                    auto_age       = VALUES(auto_age),
                    auto_education = VALUES(auto_education),
                    auto_exp_years = VALUES(auto_exp_years),
                    auto_majors    = VALUES(auto_majors),
                    auto_skills    = VALUES(auto_skills)
                ''',
                (
                    target_date, file_name, file_path, file_size, file_hash,
                    parsed['raw_text'], parsed['auto_name'], parsed['auto_gender'],
                    parsed['auto_age'], parsed['auto_education'], parsed['auto_exp_years'],
                    parsed['auto_majors'], parsed['auto_skills'],
                )
            )
        new_count += 1

    log.info(f'日期 {target_date} 扫描完成,新解析 {new_count} 份')
    return new_count


def load_resumes(target_date: date) -> list:
    """
    从库里加载某天所有简历,并 LEFT JOIN 手动编辑表和操作状态表,
    返回前端需要的完整字段列表。
    """
    with db_cursor() as cur:
        cur.execute(
            '''
            SELECT
                r.id, r.resume_date, r.file_name, r.file_size,
                r.raw_text, r.auto_name, r.auto_gender, r.auto_age,
                r.auto_education, r.auto_exp_years, r.auto_majors, r.auto_skills,
                m.manual_name, m.manual_gender, m.manual_age,
                m.manual_education, m.manual_majors,
                a.action
            FROM resume r
            LEFT JOIN resume_manual_edit m ON m.resume_id = r.id
            LEFT JOIN resume_action       a ON a.resume_id = r.id
            WHERE r.resume_date = %s
            ORDER BY r.id
            ''',
            (target_date,)
        )
        rows = cur.fetchall()

    # 格式化给前端(字符串分隔字段 → 数组;date → 字符串)
    result = []
    for r in rows:
        result.append({
            'id':              r['id'],
            'resume_date':     r['resume_date'].strftime('%Y-%m-%d'),
            'file_name':       r['file_name'],
            'file_size':       r['file_size'],
            'text':            r['raw_text'] or '',
            'auto_name':       r['auto_name'],
            'auto_gender':     r['auto_gender'] or 'unknown',
            'auto_age':        r['auto_age'],
            'auto_education':  r['auto_education'],
            'auto_exp_years':  float(r['auto_exp_years']) if r['auto_exp_years'] is not None else None,
            'auto_majors':     r['auto_majors'].split(',') if r['auto_majors'] else [],
            'auto_skills':     r['auto_skills'].split(',') if r['auto_skills'] else [],
            # 手动覆盖
            'manual_name':       r['manual_name'],
            'manual_gender':     r['manual_gender'],
            'manual_age':        r['manual_age'],
            'manual_education':  r['manual_education'],
            'manual_majors':     r['manual_majors'].split(',') if r['manual_majors'] else None,
            # 操作状态: approved / rejected / None
            'action':            r['action'],
        })
    return result


# ================================================================
# 【Flask 路由】
# ================================================================
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, template_folder=os.path.join(_BASE_DIR, 'templates'))


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/resumes')
def api_resumes():
    """
    GET /api/resumes?date=YYYY-MM-DD
    不传 date 默认今天。首次访问会自动触发扫描解析。
    """
    date_str = request.args.get('date')
    try:
        target = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else date.today()
    except ValueError:
        return jsonify({'error': 'date 格式错误,应为 YYYY-MM-DD'}), 400

    # 先扫描(只解析新增/变化的文件,快)
    scan_and_parse(target)
    # 再读取
    data = load_resumes(target)
    return jsonify({'date': target.strftime('%Y-%m-%d'), 'count': len(data), 'items': data})


@app.route('/api/parse', methods=['POST'])
def api_parse():
    """
    POST /api/parse?date=YYYY-MM-DD
    强制对某天文件夹重新扫描(主要用于用户切换历史日期时手动触发)。
    效果与 /api/resumes 相同,但语义更明确。
    """
    date_str = request.args.get('date')
    if not date_str and request.is_json:
        body = request.get_json(silent=True) or {}
        date_str = body.get('date')
    try:
        target = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else date.today()
    except (ValueError, TypeError):
        return jsonify({'error': 'date 格式错误'}), 400

    new_count = scan_and_parse(target)
    data = load_resumes(target)
    return jsonify({
        'date': target.strftime('%Y-%m-%d'),
        'new_parsed': new_count,
        'count': len(data),
        'items': data,
    })


@app.route('/api/resume/<int:resume_id>/edit', methods=['POST'])
def api_edit(resume_id):
    """保存手动编辑(姓名/性别/年龄/学历/专业)"""
    body = request.get_json(force=True, silent=True) or {}
    name      = (body.get('name')      or '').strip() or None
    gender    = body.get('gender') if body.get('gender') in ('male', 'female', 'unknown') else None
    age       = body.get('age')
    education = body.get('education') if body.get('education') in ('大专', '本科', '硕士', '博士') else None
    majors    = body.get('majors')  # 前端传数组或逗号字符串均可

    if isinstance(majors, list):
        majors = ','.join(m.strip() for m in majors if m and m.strip()) or None
    elif isinstance(majors, str):
        majors = ','.join(m.strip() for m in re.split(r'[,，]', majors) if m.strip()) or None
    else:
        majors = None

    with db_cursor() as cur:
        cur.execute(
            '''
            INSERT INTO resume_manual_edit
                (resume_id, manual_name, manual_gender, manual_age, manual_education, manual_majors)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                manual_name      = VALUES(manual_name),
                manual_gender    = VALUES(manual_gender),
                manual_age       = VALUES(manual_age),
                manual_education = VALUES(manual_education),
                manual_majors    = VALUES(manual_majors)
            ''',
            (resume_id, name, gender, age, education, majors)
        )
    return jsonify({'ok': True})


@app.route('/api/resume/<int:resume_id>/action', methods=['POST'])
def api_action(resume_id):
    """
    设置/取消操作状态。
    body: {"action": "approved" | "rejected" | null}
    action=null 表示撤销(删除记录)。
    """
    body = request.get_json(force=True, silent=True) or {}
    action = body.get('action')
    if action not in (None, 'approved', 'rejected'):
        return jsonify({'error': 'action 必须为 approved/rejected/null'}), 400

    with db_cursor() as cur:
        if action is None:
            cur.execute('DELETE FROM resume_action WHERE resume_id = %s', (resume_id,))
        else:
            cur.execute(
                '''
                INSERT INTO resume_action (resume_id, action)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE action = VALUES(action)
                ''',
                (resume_id, action)
            )
    return jsonify({'ok': True})


@app.route('/api/preview/<int:resume_id>')
def api_preview(resume_id):
    """返回 PDF 原文件,供前端 iframe 预览或下载"""
    with db_cursor() as cur:
        cur.execute('SELECT file_path, file_name FROM resume WHERE id = %s', (resume_id,))
        row = cur.fetchone()
    if not row:
        abort(404)
    if not os.path.isfile(row['file_path']):
        abort(404, description='文件不存在,可能已被移动或删除')
    return send_file(row['file_path'], mimetype='application/pdf',
                     as_attachment=False, download_name=row['file_name'])


@app.route('/api/dates')
def api_dates():
    """返回所有已有简历的日期(降序),给前端日期选择器用"""
    with db_cursor() as cur:
        cur.execute('SELECT DISTINCT resume_date FROM resume ORDER BY resume_date DESC')
        rows = cur.fetchall()
    return jsonify([r['resume_date'].strftime('%Y-%m-%d') for r in rows])


# ================================================================
# 【启动】
# ================================================================
if __name__ == '__main__':
    log.info(f'简历根目录: {Config.RESUME_ROOT}')
    log.info(f'MySQL: {Config.DB_USER}@{Config.DB_HOST}:{Config.DB_PORT}/{Config.DB_NAME}')
    log.info(f'监听: http://{Config.HOST}:{Config.PORT}')
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)
