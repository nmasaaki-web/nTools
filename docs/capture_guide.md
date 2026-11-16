# 実機撮影・動画公開ガイド（教員向け）

[← README](../README.md)

各ツールのマニュアルにはコードに基づく操作図・GIF・MP4を掲載済みです。実際のMaya画面・レンダリングではありません。以下の手順で実機画像と動画を追加できます。画像・動画を公開する際は、素材のライセンスと個人情報（APIトークン、ユーザー名、パス）に注意してください。

## 共通の準備

- 検証用シーンを保存し、File → Set Project。Maya 2027とArnoldを用意。
- シェルフ、5ツール右上のHelp、ブラウザのリンクを確認。OS標準の画面キャプチャまたは録画ソフトで、ツールのウィンドウを撮影する。
- Windows: Win+Shift+S（静止画）、macOS: Shift+Command+4（静止画）またはShift+Command+5（録画）。動画は必要なウィンドウだけを収録し、個人情報は除外する。
- 実機画像を `docs/media/<tool>/capture-01.png` などで保存し、各マニュアルに相対リンク `![実機画面](../media/<tool>/capture-01.png)` を追加する。既存の図解も残してよい。

## 撮影カット一覧

| ツール | 撮影するカット | 動画で説明する内容 |
|---|---|---|
| Sketchfab | 検索結果、選択したモデルの作者とライセンス、インポート後のビューポート | 00:00 起動、00:10 検索、00:25 ライセンス、00:40 インポート、00:55 結果確認。APIトークンを映さない。|
| PolyHaven | サムネイル一覧、LOD・解像度、インポート後、HDRI設定とレンダー | 00:00 起動、00:10 木を検索、00:25 LOD1/2K、00:40 インポート、01:00 HDRI。|
| Material Creator | Fab素材のファイル一覧、Scan後、Hypershade、Arnoldの結果 | 00:00 Megascans素材紹介、00:15 Set Project、00:30 Scan、00:45 Assign、01:00 ノードとレンダー。|
| Quadruped | ガイド配置、Build Rig、Bind後のコントローラ、IK/FK | 00:00 向き、00:15 Create Guides、00:35 ガイド位置、01:00 Build、01:20 Bind、01:40 IK/FK。転送は試験機能として別撮り。|

時間は編集用の目安です。実機動画は素材のダウンロード時間をカットしてください。

## Material Creator: 実素材デモ

対象例: [Quixel Megascans Stone Surface (Fab)](https://www.fab.com/listings/c6896470-a380-4d10-a39e-4e82cd606bae?lang=en)。自分が取得・利用可能な素材をダウンロードして展開してください。再配布可能と確認できない元データはGitHubへ追加しないでください。

通常のUI操作は [Material Creatorマニュアル](tools/material_creator.md) を参照。より簡単に実素材の動作確認をする場合は、`docs/examples/megascans_material_demo.py` をMayaのPython Script Editorから実行できます。

```python
import maya.cmds as cmds
import runpy
p = cmds.fileDialog2(fileMode=1, fileFilter='Python (*.py)', caption='Select megascans_material_demo.py') or []
if p:
    runpy.run_path(p[0], run_name='__main__')
```

取得したフォルダまたはJSONを選択すると、実際のMaterial Creatorの解析関数を使ってマップを検出し、確認後に新しい球を作成してOpenPBRを割り当てます。既存シーンの初期化・保存は行いません。作成前にシーンを保存し、Set Projectを実施してください。複数のTexture setがある場合は通常のUIで選択する仕様です。テスト球の作成に成功したら、HypershadeとArnold RenderViewで実機画像を撮影します。

## YouTube公開

各マニュアルにGitHub内のMP4（説明図による短い字幕付き動画）へのリンクがあります。YouTubeへのアップロードは教員のアカウントから行ってください。実機収録が完了したら、YouTube Studioで動画をアップロードし、公開範囲（限定公開など）を選択。発行された実URLを該当マニュアルへ `[実機チュートリアル（YouTube）](実際の動画URL)` の形式で追記します。GitHubではYouTubeリンクを開く形にしてください。未公開の動画URLは掲載しません。


## City Builderの実機撮影（追加）

- CITYボタンから起動し、右上Helpを確認。
- OSMで200〜300 m程度の範囲を指定し、ブラウザからMayaへ送信する操作、BUILD CITY、Outlinerの生成結果を撮影。
- Procedural Japanで同じ範囲を指定して、屋根・窓・道路設備の生成を比較。装飾は推定配置であることを説明。
- PLATEAUの写真付き取り込みは取得済みの適切なローカルデータを使い、出典・利用条件を確認。実際に利用できたデータと設定を記録する。
- スクリーンショット・動画は実機撮影後に `docs/tools/city_builder.md` へ追記する。
