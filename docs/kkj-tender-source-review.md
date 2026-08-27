# KKJ tender opportunity source review

## Decision

The adapter for the Japan Public Procurement Information Portal (KKJ) is implemented but disabled in production with KKJ_API_ENABLED=false.

The official service publishes a search API and requires applications using it to identify the portal as a source and link back to it. It also forbids sustained high-volume access and states that limits can be applied. The API returns public tender metadata such as the notice URL, title, buyer, geography, category, procedure, dates, and qualification when available.

## Safe field policy

The product returns only source-linked metadata. It deliberately excludes ProjectDescription and attachments because source free text can include contact details or other unnecessary personal information.

Returned fields:

- official tender key and Japanese title
- buyer, geography, category, procedure, and qualification
- available notice, opening, and delivery dates
- official notice URL, source attribution, and retrieval time

## Required confirmation before enabling production

The written terms do not clearly answer whether an independently priced API may redistribute the normalized search results. Send the following short question to the portal operator before turning on the Railway feature flag or publishing the endpoint on RapidAPI.

~~~
件名：官公需情報ポータルサイト検索APIの商用サービスでの利用について

お世話になります。

官公需情報ポータルサイト検索APIを利用し、海外の開発者向けに日本の公開調達情報を検索できるAPIサービスを検討しています。
APIの表示・レスポンスには、官公需情報ポータルサイトを情報源として明記し、各案件の元URLへのリンクを必ず表示します。サーバー負荷を避けるため、オンデマンド検索、低頻度アクセス、結果件数の制限を行います。

公告本文・添付ファイル・連絡先情報は再配布せず、件名、発注機関、地域、分類、日付、元URLなどのメタデータのみを扱う予定です。

このような、利用者からAPI利用料を受け取る形での商用利用が、利用規約の範囲内かご確認いただけますでしょうか。必要な表記やアクセス上限があれば併せてご教示ください。

よろしくお願いいたします。
~~~

## Evidence

- API guide: https://www.kkj.go.jp/doc/ja/api_guide.pdf
- Portal terms and API conditions: https://www.kkj.go.jp/s/?tc=1
