# Philocafé 原型

## 文件说明
- `index.html`：可以直接运行的页面。双击用浏览器打开就行，`assets/` 文件夹要和它放在同一个目录。
- `template.html`：源代码，方便阅读和修改。它和 index.html 的逻辑完全一样，只是里面的 `__DATA__` 是一个占位符。
- `data.json`：动画帧数据，包括每个角色用哪些帧、每帧停留多久。
- `assets/`：全部图片素材，包括场景、角色帧、头像和图标。

## 修改后怎么重新生成 index.html
把 template.html 里的 `__DATA__` 替换成 data.json 的内容即可，例如：

    python3 -c "t=open('template.html').read(); d=open('data.json').read(); open('index.html','w').write(t.replace('__DATA__', d))"

## 关于 AI 回复
- 在 claude.ai 上打开时，页面通过 `window.claude.use("sample")` 调用 Claude，右上角显示 Live。
- 在本地或其他网站打开时，没有这个接口，页面会自动切换成预设台词，右上角显示 Demo。
- 想接自己的后端，把 template.html 里 `send()` 函数中的 `await sample(prompt, ...)` 换成 `fetch` 调用你的 API 就行，其余逻辑不用改。注意不要把 API key 写在前端代码里。

## 快捷入口
在网址后面加 `#socrates`、`#montaigne`、`#schopenhauer`、`#seneca`、`#epictetus`、`#notes` 或 `#distress`，可以直接跳到对应页面。
