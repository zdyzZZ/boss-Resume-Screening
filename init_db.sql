-- ==========================================
-- 简历筛选系统 - 建表脚本
-- 数据库: cx
-- ==========================================

USE cx;

-- ------------------------------------------
-- 简历主表
-- ------------------------------------------
DROP TABLE IF EXISTS resume_action;
DROP TABLE IF EXISTS resume_manual_edit;
DROP TABLE IF EXISTS resume;

CREATE TABLE resume (
    id              BIGINT          NOT NULL AUTO_INCREMENT COMMENT '主键',
    resume_date     DATE            NOT NULL                COMMENT '简历所属日期(=文件夹日期)',
    file_name       VARCHAR(512)    NOT NULL                COMMENT '文件名(带 .pdf 后缀)',
    file_path       VARCHAR(1024)   NOT NULL                COMMENT '文件绝对路径,用于预览/下载',
    file_size       BIGINT          DEFAULT NULL            COMMENT '文件大小(字节)',
    file_hash       CHAR(32)        DEFAULT NULL            COMMENT '文件 MD5,用于判断内容是否变化(决定是否重新解析)',

    raw_text        MEDIUMTEXT      COMMENT '简历全文纯文本,用于前端筛选时按关键词匹配',

    auto_name       VARCHAR(64)     DEFAULT NULL            COMMENT '自动识别的姓名',
    auto_gender     VARCHAR(16)     DEFAULT 'unknown'       COMMENT '自动识别性别: male/female/unknown',
    auto_age        INT             DEFAULT NULL            COMMENT '自动识别年龄',
    auto_education  VARCHAR(16)     DEFAULT NULL            COMMENT '自动识别学历: 大专/本科/硕士/博士',
    auto_exp_years  DECIMAL(4,1)    DEFAULT NULL            COMMENT '自动识别工作年限',
    auto_majors     VARCHAR(512)    DEFAULT NULL            COMMENT '自动识别专业,多个用英文逗号分隔',
    auto_skills     TEXT            DEFAULT NULL            COMMENT '自动识别技能,多个用英文逗号分隔',

    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP                      COMMENT '首次入库时间',
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最后解析时间',

    PRIMARY KEY (id),
    UNIQUE KEY uk_date_file (resume_date, file_name)        COMMENT '同一天同一文件名只存一条,重复解析走 upsert',
    KEY idx_date (resume_date)                              COMMENT '按日期查询加速'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='简历主表,存自动解析结果';


-- ------------------------------------------
-- 手动编辑覆盖表
-- ------------------------------------------
CREATE TABLE resume_manual_edit (
    resume_id        BIGINT         NOT NULL                COMMENT '对应 resume.id',
    manual_name      VARCHAR(64)    DEFAULT NULL            COMMENT '手动修正姓名,NULL=未修改',
    manual_gender    VARCHAR(16)    DEFAULT NULL            COMMENT '手动修正性别: male/female/unknown',
    manual_age       INT            DEFAULT NULL            COMMENT '手动修正年龄',
    manual_education VARCHAR(16)    DEFAULT NULL            COMMENT '手动修正学历',
    manual_majors    VARCHAR(512)   DEFAULT NULL            COMMENT '手动修正专业,多个用英文逗号分隔',

    updated_at       DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最后修改时间',

    PRIMARY KEY (resume_id),
    CONSTRAINT fk_manual_resume FOREIGN KEY (resume_id) REFERENCES resume(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='简历手动编辑覆盖表';


-- ------------------------------------------
-- 操作状态表(全局共享,所有用户看到同样的通过/否决状态)
-- ------------------------------------------
CREATE TABLE resume_action (
    resume_id    BIGINT         NOT NULL                COMMENT '对应 resume.id',
    action       VARCHAR(16)    NOT NULL                COMMENT '操作类型: approved=人工通过 / rejected=人工否决',
    operator     VARCHAR(64)    DEFAULT NULL            COMMENT '操作人(预留,暂无登录系统)',
    updated_at   DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '操作时间',

    PRIMARY KEY (resume_id),
    CONSTRAINT fk_action_resume FOREIGN KEY (resume_id) REFERENCES resume(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='简历操作状态表';
