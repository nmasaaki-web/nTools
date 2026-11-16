# PolyHaven Asset Browser v5.2

[← nTools トップへ戻る](../../README.md)

![PolyHaven](../../scripts/ntools/icons/polyhaven.png)

Poly Havenのモデル、植物、サーフェス、HDRIをMayaから検索・取得し、OpenPBRやArnoldライトを設定します。ダウンロード済みのローカルアセット（FBX/OBJ、テクスチャ等）も扱えます。

## クイックガイド（図解・GIF・動画）

ウィンドウ右上の **Help** からこのページを開けます。

![PolyHaven Asset Browser 操作の流れ](../media/polyhaven/quick-guide.gif)

[静止画 STEP 1](../media/polyhaven/step-1.png) · [STEP 2](../media/polyhaven/step-2.png) · [STEP 3](../media/polyhaven/step-3.png) · [STEP 4](../media/polyhaven/step-4.png) · [MP4動画を開く／ダウンロード](../media/polyhaven/quick-guide.mp4)

> 図解・GIF・MP4は実際のソースコードのボタン名・設定に基づく操作説明です。Mayaの実機キャプチャや実行結果ではありません。

## 1. 準備

Mayaで **File → Set Project** を実行し、シーンを保存します。Arnold / OpenPBRが使用できる環境で、nToolsシェルフの **PH** を押します。オンライン機能にはインターネット接続が必要です。Poly Havenの公開APIを使用し、個人APIトークンの入力はありません。

## 2. モデル・植物を読み込む

1. `Poly Haven Assets` タブを選択します。
2. 検索欄に `tree`、`rock` などを入力し、必要に応じて `3D Models` / `Plants` / `Surfaces` で絞り込みます。`Previous` / `Next` でページ移動します。
3. サムネイル一覧からアセットを選びます。
4. 右側の `Mesh LOD / Tier` と `Texture resolution` を設定します。授業ではまず初期値のLOD 1・2Kを推奨します。
5. `Copy textures to Maya project` をONにしたまま、インポートボタン `DOWNLOAD & IMPORT` を押します（ローカルでは `IMPORT / CREATE OPENPBR`）。
6. Set Projectの確認画面が出たら、表示されたプロジェクトを確認して「はい」。ダウンロード・インポート完了後、形状とマテリアルを確認します。

オンラインのLODはLODラベル付きファイルがある場合に有効です。指定解像度・LODがない場合は利用可能な近い候補が選ばれることがあります。ログで実際のファイルを確認してください。

`Download only` は取得のみ行い、後からローカルライブラリで読み込む場合に便利です。`Cancel download` はダウンロードのキャンセル、`Open asset page` は元サイトの確認に使います。ダウンロード中にシーンやプロジェクトを変更すると、自動インポートが省略される場合があります。

## 3. サーフェス（床・壁等）を作成する

1. Mayaでマテリアルを割り当てるポリゴンメッシュまたはフェースを選択します。
2. `Poly Haven Assets` の `Surfaces` からテクスチャ素材を選択します。
3. `Surfaces: assign to selection` をONにしてインポートします。
4. 生成されたOpenPBRとテクスチャの接続をHypershadeで確認します。

割り当て先がない場合は処理を中止する警告が表示されます。マテリアルだけ生成したいときは `Surfaces: assign to selection` をOFFにしてください。

## 4. HDRIで照明を作る

1. `Poly Haven HDRIs` タブを選択し、空や屋外のHDRIを探します。
2. `HDRI resolution`（初期4K）、`Exposure (EV)`、`Rotation (degrees)` を設定します。
3. `Visible in camera` で背景として見せるかを設定します。`Replace selected / first existing Skydome` は初期ONです。既存のSkydomeを変更したくない場合はOFFにします。
4. `DOWNLOAD & CREATE SKYDOME` を押し、プロジェクトを確認します。Arnold Skydome Lightが作成、または既存の編集可能なSkydomeが更新されます。
5. Arnold RenderViewで確認し、明るさや向きを調整します。

ローカルの `.exr` / `.hdr` は `Import local EXR / HDR…` から読み込めます。HDRIはモデルのコピー設定にかかわらずプロジェクトのsourceimages内の `AssetBrowser/HDRIs/` にコピーされます。

## 5. ローカルライブラリを使う

1. ZIPなどを展開してから `Add Folder…` でアセットのフォルダを登録します。
2. `Local Library` タブで検索・選択します。`Refresh` で再走査します。
3. `Model variant`、LOD、解像度、その他の設定を確認し、`IMPORT / CREATE OPENPBR` を押します。

`Remove` は登録フォルダをライブラリから外すための操作です。Fab/Megascansなどのローカルデータは入手元のライセンスを確認してください。マテリアルだけ作成する場合は [Material Creator](material_creator.md) も利用できます。

## 6. 主な設定

| 設定 | 初期値・役割 |
|---|---|
| Mesh LOD / Tier | LOD 1。対応するメッシュの詳細度を選択。 |
| Texture resolution | 2K。大きいほど容量・VRAM負荷が増える。 |
| Normal convention | Auto (file name)。必要に応じOpenGL / DirectX。 |
| Enable Displacement | OFF。高さ、Height midpoint、Subdiv iterationsを調整。 |
| Import as Arnold Stand-in | OFF。対応モデルをArnoldのASSに書き出してスタンドイン化する。 |
| Copy textures to Maya project | ON。テクスチャをプロジェクト内へコピーする。 |
| Surfaces: assign to selection | ON。サーフェス素材を選択メッシュに割り当てる。 |

## 7. 保存とトラブル対処

- モデル等のキャッシュはMayaユーザーアプリディレクトリの `NativeAssetBrowser/PolyHaven/` を使用します。`Open Cache` で開けます。
- コピーをONにしたテクスチャはプロジェクトのsourceimages内 `AssetBrowser/` に保存されます。スタンドインは `data/AssetBrowser/standins/` に保存されます。シーンだけでなく、必要なプロジェクトファイルも提出・移動してください。
- `Repair Texture Paths` はシーン全体の通常のfileテクスチャを現在のプロジェクトにコピーしてパスを変更する機能です。シーンを保存してから実行し、ログを確認してください。UDIM・連番・参照やロックされたパス等は自動修復されない場合があります。
- カタログの取得に失敗したら `Refresh API` を試します。macOSでも通信できるようシステムcurlを使用しますが、学校のプロキシや証明書の設定によって失敗することがあります。
- ArnoldやFBX関連のエラーはPlug-in Managerとログを確認してください。すべての素材の特殊なマップが自動接続されるわけではありません。

[← ツール一覧へ](../../README.md) · [Material Creator →](material_creator.md)
