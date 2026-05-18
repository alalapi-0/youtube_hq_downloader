# Vimeo 寻源 Prompt 模板

把下面模板作为控制台需求输入的基础版本，再替换品牌、品类和风格词：

```text
请只在 Vimeo 上寻找广告/商品/品牌视频 URL。

目标：
我要找 [品类/品牌/风格] 的高质量官方广告或品牌片，优先 product film、campaign film、brand film、packshot、macro、still life、studio lighting、hero product shot。
页面文本最好能出现 advertisement、commercial、campaign、Agency、Creative Director、Art Director、Director、Production Company、DOP、Editor、Colorist、Post、VFX 等广告制作特征。

硬性条件：
1. 平台必须是 Vimeo，URL 必须是 https://vimeo.com/数字 ID 的视频页。
2. 必须能从页面标题、摘要或搜索结果证据中确认 4K / 2160p / UHD；只有 720p、1080p、HD 或无法确认清晰度的不要。
3. 时长必须能确认在 60 秒以内；无法确认时长的不要。
4. 发布时间或上传时间必须能确认在最近两年内；无法确认日期的不要。
5. 必须能看到广告/商业片证据：Vimeo 广告提示、advertisement、commercial、campaign、product film，或 Agency / Production Company / Director / DOP / Colorist / Post / VFX 等制作 credit。
6. 排除 AI generated、review、unboxing、vlog、behind the scenes、compilation、showreel、reupload、fanmade、full show、interview、tutorial、news。

偏好：
- 官方品牌账号、广告代理商、制作公司、导演/摄影师作品页。
- 商品明确露出、画面干净、棚拍、商业感强、低运动、无大面积字幕水印。
- 奢侈品、美妆、香水、珠宝腕表、汽车、数码产品等高端商品广告。

请优先返回能同时证明 URL、4K、时长、发布时间、商业广告属性的结果。
```

更具体的例子：

```text
请只在 Vimeo 上寻找高端奢侈品官方广告，任意奢侈品牌都可以，优先香水、包袋、珠宝、腕表、彩妆产品 film。
必须是 Vimeo 视频页，必须有 4K / 2160p / UHD 证据，时长 60 秒以内，发布时间两年内。
排除 AI、review、unboxing、vlog、behind the scenes、compilation、showreel、reupload、fanmade、full show。
偏好 product film、campaign film、brand film、studio lighting、macro、packshot、still life、hero product shot、official commercial。
强优先页面描述里有 advertisement、Agency、Creative Director、Art Director、Director、Production Company、DOP、Editor、Colorist、Post、VFX、Fall 2025 Campaign 这类广告制作信息的 Vimeo 视频。
```
