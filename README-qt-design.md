# Qt 界面设计

## 使用的 skill

本轮使用 `zxzvsdcj/qt-ui-engineering`，重点参考 QWidget、PySide6、QSS、QStyle、spacing-and-layout、visual-system 和 ui-review-checklist。

检索时还比较了 `Boyjingweizhang/qt-widgets-agent-skills` 的分析、原型、实现和审查流程；本轮未采用该完整流程。

## 设计约束

- 保留 PySide6 6.8.3、QWidget、现有 API、授权、设置、任务与导出行为。
- 白色控件、灰色工作区、紫色操作强调；选中下拉项不加底色。
- 用边框标记键盘焦点、箭头区域表达展开、文字颜色表达选择。
- 表单按关系使用 8/12/16 逻辑像素间距；缩小装饰性空白，保留操作目标尺寸。
- 主题由 `qt_theme.py` 管理；下拉绘制与宽度建议由 `qt_controls.py` 管理。
- 输入框、下拉框根据内容提供建议宽度，由布局分配实际空间；长文本弹出列表有宽度上限。
- TTS 参数面板宽度范围 340–460，文案区域优先获得剩余空间。

## 本地验证

123 项单元测试通过。四个处理模块在 1170×850 最小窗口检查操作按钮几何范围；离屏 150% 缩放检查下载页。实际 QWidget 截图检查下载页、TTS 页面和下拉列表。

真实跨显示器移动、125%/200% 系统缩放及用户视觉验收尚未验证。界面验证不调用付费 API。
