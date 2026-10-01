/**
 * stylelint.config.mjs — 设计系统硬约束
 * ----------------------------------------------------------------------------
 * 放在项目根目录。这是四层约束里的**第三层（可执行检查）**。
 *
 * 它为什么比 SKILL.md 里的文字规则强：文字规则被违反时，没有任何事情发生；
 * 这里被违反时，命令**报错并返回非零退出码** —— 可以挂到 CI 或 pre-commit 上。
 * 一句话规则弱于一个会失败的构建。
 *
 * 安装：
 *   npm i -D stylelint stylelint-config-standard postcss-html
 * 运行：
 *   npx stylelint "src/**\/*.{css,vue}"
 * package.json：
 *   "lint:css":     "stylelint \"src/components/ui/**\/*.vue\" \"src/components/layout/**\/*.vue\""
 *   "lint:css:all": "stylelint \"src/**\/*.{css,vue}\""
 *
 * ⚠️ 迁移期策略：`lint:css` 只卡**新代码**（ui/ 与 layout/），legacy 的
 * `src/styles/main.css` 用 `npm run audit` 跟踪收敛进度，不进这个硬门 ——
 * 否则一开就是 600+ 条报错，人会习惯性忽略输出，等于没开。
 * 阶段二把 main.css 收敛完后，把 `lint:css` 的 glob 换成 `src/**\/*.{css,vue}`。
 *
 * ⚠️ 落地策略：**先只开 error**，把现有违规清完。一次性开满会让人
 * 习惯性忽略输出 —— 那就等于没开。建议首批只保留第 1、2、4、6 组。
 */
export default {
  extends: ['stylelint-config-standard'],

  rules: {
    /* ======================================================================
     * 1. 禁止颜色字面量（AP-02 / AP-04）
     * ----------------------------------------------------------------------
     * 只允许 var() 与透明/继承类关键字。
     * 内容色（图表数据、用户头像哈希色）用行内豁免：
     *   background: #ff0000; // stylelint-disable-line -- 图表数据色
     * ==================================================================== */
    'declaration-property-value-disallowed-list': {
      '/^.*$/': [
        '/#[0-9a-fA-F]{3,8}\\b/',
        '/\\brgba?\\s*\\(/',
        '/\\bhsla?\\s*\\(/',
      ],
      // 无障碍：焦点环是键盘用户唯一的导航手段，不要删掉（AP-16）
      'outline': ['none'],
      'outline-style': ['none'],
      // 魔法 z-index：必须是 var(--z-*)（AP-06 的近亲）
      'z-index': ['/^\\d+$/'],
    },

    /* ======================================================================
     * 2. 禁止设计维度写裸 px（AP-06 / AP-07 / AP-09）
     * ----------------------------------------------------------------------
     * 这些属性只允许 var()、0、%（var 无单位，所以不会被误伤）。
     * 注意：**不包括** border-width —— 1px 边框是合法例外。
     * ==================================================================== */
    'declaration-property-unit-disallowed-list': {
      'padding': ['px', 'rem', 'em'],
      'padding-top': ['px', 'rem', 'em'],
      'padding-right': ['px', 'rem', 'em'],
      'padding-bottom': ['px', 'rem', 'em'],
      'padding-left': ['px', 'rem', 'em'],
      'margin': ['px', 'rem', 'em'],
      'margin-top': ['px', 'rem', 'em'],
      'margin-right': ['px', 'rem', 'em'],
      'margin-bottom': ['px', 'rem', 'em'],
      'margin-left': ['px', 'rem', 'em'],
      'gap': ['px', 'rem', 'em'],
      'row-gap': ['px', 'rem', 'em'],
      'column-gap': ['px', 'rem', 'em'],
      'font-size': ['px', 'rem', 'em'],
      'border-radius': ['px', 'rem', 'em'],
      'box-shadow': ['px'], // 阴影里允许 0，允许 var()
    },

    /* ======================================================================
     * 3. 禁止 !important（AP-21）
     * ==================================================================== */
    'declaration-no-important': true,

    /* ======================================================================
     * 4. 禁止重复选择器（AP-10 的机器检测 —— 本项目最该开的一条）
     * ----------------------------------------------------------------------
     * 它检测的是"同一个选择器在同一个文件里被定义了两次"。
     * 这正是 "refinement 追加块" 的指纹：
     *   .composer { ... }        <- 第一次
     *   ...
     *   .composer { ... }        <- 第四次的覆盖
     * 阈值 0：任何重复都报错。
     * ==================================================================== */
    'no-duplicate-selectors': true,
    'no-descending-specificity': true,
    'no-duplicate-at-import-rules': true,
    'block-no-empty': true,

    /* ======================================================================
     * 5. 禁止魔法数值
     * ----------------------------------------------------------------------
     * z-index 必须走 --z-*，否则会长出 9999 这类值。
     * （这条已合并进规则 1 的对象里，见文件末尾说明）
     * ==================================================================== */

    /* ======================================================================
     * 6. 选择器纪律（AP-20 的间接约束）
     * ----------------------------------------------------------------------
     * 深层嵌套 = 无法安全修改 = 只能追加覆盖 = 回到 AP-10。
     * 不需要 !important 的 CSS，几乎总是选择器层级合理的 CSS。
     * ==================================================================== */
    'selector-max-id': 0,
    'selector-max-compound-selectors': 4,
    'selector-max-specificity': '0,4,0',
    'max-nesting-depth': 3,

    /* ======================================================================
     * 7. 格式（沿用 standard，按实际需要放宽）
     * ----------------------------------------------------------------------
     * 下面几条都是「跑起来才发现」的：standard 的默认值与真实组件写法冲突，
     * 而冲突的一方是 standard 错了。装好之后**务必真的跑一次**
     * `npx stylelint "src/**\/*.vue"`，否则这些冲突不会暴露 ——
     * 一份从没被执行过的配置，和没有配置是一样的。
     * ==================================================================== */
    'comment-empty-line-before': null,
    'custom-property-empty-line-before': null,

    // BEM：放行 ui-button / ui-button__icon / ui-button--sm。
    // standard 默认只认 kebab-case，会把整套 BEM 判成 86 个错误。
    // 这条正则只拦真正想拦的东西：camelCase 与 PascalCase 的漂移。
    'selector-class-pattern': '^[a-z][a-z0-9]*(?:[-_]{1,2}[a-z0-9]+)*$',

    // 降级为 warning：这条规则确实能抓到真实缺陷，但它与本项目
    // 「状态必须显式排序（default → hover → focus → active → disabled）」
    // 的约定直接冲突 —— 按状态顺序写就必然违反它。保留为提示，不阻塞构建。
    'no-descending-specificity': [true, { severity: 'warning' }],

    // currentColor 是规范里的标准拼写，放行 lowercase 检查
    'value-keyword-case': ['lower', { ignoreKeywords: ['currentColor'] }],

    // 原生 select 的外观复位必须带 -webkit- 前缀才能在 Safari 生效
    'property-no-vendor-prefix': [true, { ignoreProperties: ['-webkit-appearance'] }],
  },

  ignoreFiles: [
    'node_modules/**',
    'dist/**',
    '**/*.min.css',
    // token 文件本身当然要写颜色和 px —— 它就是唯一真相源（AP-01）
    'src/styles/tokens.css',
  ],

  overrides: [
    {
      files: ['**/*.vue'],
      customSyntax: 'postcss-html',
    },
  ],
};

/* ============================================================================
 * stylelint 原生覆盖不到、必须靠 scripts/audit-css.mjs 的两项检查：
 *   - `:root` 块数量（AP-01）—— stylelint 没有"跨块计数"能力
 *   - 颜色近重复聚类（AP-02 的深层形态）—— 需要计算色距，不是模式匹配
 *   - 近白背景数量、字号档位分布（AP-07 / AP-08）
 * 这四项是 audit 脚本存在的理由。
 *
 * 校验本配置本身是否可用：
 *   npx stylelint --print-config src/styles/main.css > /dev/null
 * 如果报 "Unknown rule"，说明该 rule 在当前 stylelint 大版本里不存在，
 * 删掉它 —— 不要留着一个从没被执行过的规则假装有约束。
 * ==========================================================================*/
