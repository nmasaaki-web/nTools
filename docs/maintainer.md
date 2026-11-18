# nTools 管理者向けガイド v1.0.11

## 公開・移行

ZIPの中身を既存のGit作業フォルダに上書きコピーする。`.git` は維持する。`git status` を確認し、以下を実行する。

```bash
git add .
git commit -m "Release nTools v1.0.11 - Live tool update"
git push
```

v1.0.0〜1.0.2から移行する場合は、旧Updateを使用せず、新ZIPのinstall.pyから導入する。異常なタブ名がある場合はREADMEの復旧手順を先に実施。

## 実機検証手順（Windows / macOS）

1. Mayaの設定フォルダをMaya終了中に別の場所へコピーし、復旧できるようにする。既存の制作シーンは保存する。可能なら検証専用OSユーザーを使用する。
2. 起動してFile等のメニュー、メニューセット、他シェルフを確認。新規環境でinstall.pyを実行し、利用上の注意を確認する。未チェック時に両導入ボタンが無効、チェックで有効、チェック解除で無効、Cancel／閉じるで変更なしを確認する。同意後にInstall + Shelfを選択する（Files Onlyによる段階テストも可能）。
3. 再起動せず5ツール、Separator、Help、Uninstall、Updateを確認し、各ツールの起動を試す。Files Onlyを選んだ場合は管理コードからRepair Shelfを選択する。
4. Maya再起動後にシェルフが残ること、File等のメニューが表示されることを確認。
5. v1.0.3〜1.0.7の5・6・7ボタン環境からUpdate → 再起動 → Updateを試す。SF → PH → CITY → MAT → RIG → Separator → Help → Uninstall → Updateの順、重複なし、元のツールとUpdateボタンの維持、再起動後の保持を確認。8ボタン＋Separator環境では通常更新でシェルフ保存が発生しないこと、カスタムボタンがある場合は自動同期しないことを確認。
6. Uninstallは2段階：案内ウィンドウで「コピー」を押し、コードがクリップボードに入ることを確認。メモ帳などに保存してからMaya標準Shelf EditorでnToolsだけを削除・保存し再起動。Pythonタブでコピーしたコードを実行し、確認後に本体をバックアップへ移動する。自動シェルフ削除は行わない。

## 変更履歴と設計

- 1.0.0: 初回配布。通常更新でもシェルフを再構築。
- 1.0.1: パッケージ置換をシェルフ操作から分離。既存タブは再構築しない。修復は欠落タブに限定。Maya公式addNewShelfTab / deleteShelfTabを使用し、独自deleteUIでタブを削除しない。メニューセットを読み取り確認し、関連設定をバックアップ。全体設定の自動リセットなし。
- 1.0.2: Uninstallボタンを追加。
- 1.0.3: saveShelfの二重拡張子問題を修正。異常なシェルフ名・ファイルを検出して中止。Uninstallは標準Shelf Editorを使う2段階方式に変更。
- 1.0.4: 初回のInstall + Shelfを既定にし、再起動不要と明記。Uninstall案内をコード欄・コピーボタン付きQtダイアログに変更。削除処理は1.0.3の安全な2段階方式を維持。
- 1.0.5: 4ツールの右上に個別Help、シェルフにHelp（Uninstallの左）を追加。ツールの主要処理と既存アイコンは維持。旧5・6ボタンからAdd Help Buttonで明示的に移行。マニュアルに操作図・GIF・MP4と実機撮影ガイドを追加。

- 1.0.7: RIGとHelpの間にMaya標準の縦Separatorを追加。新規登録・既存シェルフ同期・所有判定に対応。
- 1.0.6: Updateに管理ボタン同期を追加。最新版でも同期し、既知の旧構成にHelp / Uninstallのみ追加。MayaのshelfLayout positionで並べ、既存Updateボタンは変更しない。シェルフ全体の削除・再構築なし。

- 1.0.8: City Builder v2.4.1（nTools起動・個別Help）とアイコン・日本語マニュアルを追加。既知の旧構成にCITYを追加し、MATの左へ移動。元の4ツールは削除・再作成しない。

- 1.0.9: インストール確認をQtの同意ダイアログに変更。READMEの免責全文をオフライン表示し、未同意では本体導入・シェルフ登録を実行しない。通常Updateは変更なし。READMEの免責を改訂する際はinstall.pyのINSTALL_NOTICEも同期してrelease.pyを実行する。

- 1.0.10: SketchfabにKHR_materials_pbrSpecularGlossiness対応を追加。
- 1.0.11: Update時の一律再起動要求を廃止。変更されたモジュールが未使用か終了済みであることを確認し、パッケージ置換後のdeferredコールバックで管理モジュールを再読み込み、変更されたツールモジュールのみimportキャッシュから取り除く。次回ボタン押下時に新しいコードが読み込まれる。処理中や開いているツールウィンドウがあれば、ファイルの更新前に中止して閉じるよう案内。読み込みの切替失敗は安全側に倒して再起動要求。初回導入は従来どおり再起動不要。旧v1.0.10からの最初の更新だけは旧Updaterの仕様上、再起動が必要。

### Live update 実機検証

1. v1.0.11をインストールした検証用Mayaで、全ツールを閉じた状態から次の更新版を配信し、Update 1回後に再起動せずツールが新コードで起動することを確認。
2. SketchfabまたはPolyHavenを開いた状態でそのツールのコードを変更した更新を配信し、Updateがファイル置換前に中止してウィンドウを閉じるよう案内することを確認。
3. City Builderで処理中のUpdateは中止され、処理が完了してウィンドウを閉じてからのUpdateに成功することを確認。
4. Quadruped Quick Rigを閉じてUpdateし、次のRIGボタン1回でウィンドウが1つだけ起動することを確認。
5. 最新版のUpdateではファイルを置換せず、通常のシェルフ同期のみ行われること、Fileメニューと他シェルフが再起動後も正常であることを確認。
6. v1.0.10からv1.0.11への最初の更新は、旧Updaterが再起動を求めることを確認。その再起動後のv1.0.11からは上記の仕様を検証。

## 次のリリース

ツール本体を `scripts/ntools/tools/` 内の該当ファイルで上書きする。必要に応じ `release.py` のTOOLSリストでバージョン、説明等を修正する。アイコンは `scripts/ntools/icons/` に配置。配布に含めるファイルのハッシュを生成する：

```bash
python release.py 1.0.11
git add .
git commit -m "Release nTools v1.0.11"
git push
```

更新時はバージョン番号を必ず増加させる。v1.0.8のUpdateは既知の旧構成に不足するCITY・管理ボタン・Separatorを自動追加する。旧版からv1.0.8への移行時は再起動後のUpdateがもう一度必要。旧版が構成不一致を表示しても本体更新済みなら再起動してUpdateを実行する。今回のCITY以外の将来の新しいツールの追加・削除やボタンの順序・説明・アイコンファイル名変更がある場合、学生は更新後に既存nToolsタブをMayaのShelf Editorで削除・保存し、再起動後Repair Shelfを実行する。通常のツール本体変更だけなら不要。既存ボタンの説明やバージョン表記（旧版シェルフ）は自動更新されない。

## 復旧

- ファイル更新中の失敗では、旧パッケージへの復元を試みる。失敗ログとバックアップのパスをScript Editorで確認する。
- 新規シェルフ登録中に問題が発生した場合、本体を保持する。部分的なシェルフを自動削除しない。MayaのUIが正常ならShelf EditorでnToolsだけを整理する。
- UIバックアップは `cmds.internalVar(userScriptDir=True)` の `.ntools-ui-backups` にある。必要に応じてMaya終了中に、現行設定を別途バックアップしてから復元する。自動復元は行わない。バックアップ対象は存在するuserPrefs.mel、menuSetPrefs.mel、windowPrefs.mel、userHotkeys.mel、shelf_nTools.mel。完全なprefsバックアップではない。
- Maya.envを編集する処理はない。設定の破損原因が特定できない場合、Mayaの設定フォルダ全体を別名に変更して再起動し、必要な設定のみ戻す。
- アンインストール後の本体バックアップは `.ntools-uninstalled-*`。手動復元するならMayaを終了し、既存ntoolsフォルダがないことを確認してから名前をntoolsに戻し、再起動後Repair Shelf。

## 検証範囲

Python構文、ハッシュ、ZIP、ファイル置換、模擬Maya APIによる処理のテストを実施可能。実際のMaya 2027.2のUI動作、再起動後の保持、Mac環境およびGitHub接続は実機検証が必要。

旧版の復旧手順とv1.0.8の検証条件はREADMEを参照。`saveShelf` の保存先は拡張子なしとする。


## v1.0.12 — データ集合ツール（Data Collector）

- 追加したファイル：`scripts/ntools/tools/data_collector.py`、`scripts/ntools/icons/collector.png`、`docs/tools/data_collector.md`。
- シェルフ順序：**SF → PH → CITY → MAT → RIG → 集合！ → Separator → Help → Uninstall → Update**。
- 旧版（1.0.11）からはUpdate後に本体が切り替わり、不足している集合ボタンを同期します。旧版からの初回更新ではアクティブなツールの終了が必要な場合があります。
- 本ツールは、Maya標準・一部Arnold/USDキャッシュの既知ファイル属性のみを対象にします。 `.ass` や参照シーン内部の外部ファイルを再帰的に書き換えるものではありません。
- 授業では、保存済みシーンのバックアップを確認してからコピー・再リンクしてください。実機検証の済んでいない機能は必ず小さなテストシーンで試してください。
- Maya非依存のテスト：`python -m unittest discover -s tests -v`。Maya環境では、参照シーン、画像シーケンス、マルチドライブ、Unicodeファイル名、バックアップ、UDIMの個別試験を推奨。


## v1.0.22: ワンクリックUninstall

- **Uninstall**からMaya公式`deleteShelfTab "nTools"`を遅延実行します。標準コマンド自体が確認ダイアログを出すため、独自のYes/Noダイアログを重ねません。キャンセル時はnToolsを維持します。
- シェルフが登録されていないFiles Only状態では、nToolsのYes/Noダイアログを1回表示します。
- 動作中のツールや不明なシェルフボタンがあると中断します。削除前に既存UI設定をバックアップし、削除後に登録情報が残っていないことを確認してから本体を`.ntools-uninstalled-*`へ名前変更します。元ファイルは物理削除しません。
- nToolsのシェルフそのものから実行されるため、削除処理は`cmds.evalDeferred`で実行し、ボタンコールバック中にその親を破棄しません。
- **検証必須**：Maya 2027のWindowsおよびMacで Yes/Noを選択した際の動作、再起動後のFileメニューと他シェルフ、nToolsシェルフが復元されないことを確認する。まずは検証用のユーザープリファレンスとシーンで行う。


## v1.0.25: Stand-in Look Controller

- `standin_look_controller.py` をnTools本体と共に配布。PolyHavenの上部ボタンから起動。シェルフ構成は変えない。
- ASS生成前にOpenPBRの未接続パラメータへ `aiUserDataFloat` を接続し、Base Colorに中立の `aiColorCorrect` を追加。元テクスチャの接続を維持する。
- ASS生成後にaiStandInへ `mtoa_constant_ntools_*` と `ntoolsLookProfile` を作成。SHAPE属性はMayaシーンに保持。調整はASS本体を編集しない。
- **実機必須テスト:** Arnoldで1本の葉材のWeight=0→0.3、SSS Saturation 1→0.7、Surface Exposure 0→1を試し差異を確認。保存・再読込、3本独立ASS、同一ASSを2個配置した場合、Auto Instancing ON/OFF、MASH経由での動作をテスト。未実施なら授業用Public版へ公開しない。
- ソースパス・FBXの幹や葉の材質判定、既存ASSの仕様は変更していない。新機能を使うにはv1.0.25以降で改めてASSを作る必要がある。
- MtoAごとの `mtoa_constant_` user data転送や `aiColorCorrect.exposure` 属性の実機検証が重要。非対応の場合は操作を無効化、別のエクスポート方法を検討する。

## v1.0.26: SSS Color Exposure for Arnold Stand-in

- Plant SSSの既存aiColorCorrect.exposureへ `aiUserDataFloat` を接続（デフォルト0、従来表示と等価）。`mtoa_constant_ntools_sss_exposure`でStand-inごとに調整する。
- `CONTROLS` ホワイトリストに `sss_exposure` を追加。カラー補正ノードや元Diffuseテクスチャは共有したまま。
- `read_profile` は、古いschema1でチャンネルがないASSには新項目を出さない。古いASSを無言でサポート扱いにしない。
- 旧ASSへのチャンネル付与は行わない。v1.0.26以降で再生成したASSのみ新しいSSS Exposureを操作できる。
- 必ずMaya 2027+MtoAの実機Arnoldレンダリングで確認してから授業配布する。
