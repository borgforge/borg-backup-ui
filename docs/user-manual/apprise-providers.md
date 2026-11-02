# Apprise 2.1.0 providers / Anbieter (#672)

This package exposes **158 providers** through Settings > Notifications. The
existing base-package strategy is retained; optional dependencies from
`all-plugins` are not added. Search by provider name or URL scheme to select a
provider. The generic URL entry remains available.

Dieses Paket bietet **158 Anbieter** unter Einstellungen > Benachrichtigungen.
Die bisherige Paketstrategie bleibt bestehen; optionale Abhängigkeiten aus
`all-plugins` werden nicht ergänzt. Suche nach Anbietername oder URL-Schema,
um einen Anbieter auszuwählen. Die generische URL-Eingabe bleibt verfügbar.

New since 1.13.1 / Neu seit 1.13.1: **AMQP, Better Stack, Delta Chat, GitHub,
GoAlert, Gorush, LFG Alarm, Mobile Message, OneBot, Simplepush, Squadcast, Telnyx,
WPUSH, YouLMK, Zalo, Zoho Cliq, ilert, incident.io**.

Removed in 2.1.0 / In 2.1.0 entfallen: **Amazon Chime** (`chime://`). Existing
profiles show a reconfiguration warning; saved settings and secrets are kept.
Choose another provider to restore delivery. **NotificationAPI** (`napi://`,
`notificationapi://`) remains retired; use new Pingram credentials or another
provider. Changing only the URL scheme is not sufficient.

Bestehende Chime-Profile erhalten einen Hinweis zur Neueinrichtung mit einem
anderen Anbieter. Einstellungen und Secrets bleiben erhalten. NotificationAPI
bleibt eingestellt; dafür sind neue Pingram-Zugangsdaten oder ein anderer
Anbieter nötig. Ein bloßer Wechsel des URL-Schemas reicht nicht aus.

The following providers are **not available in the base bundle**, as before:
MQTT, XMPP, Growl, SMPP, blink(1), Session Open Group Server,
Vapid Web Push, Firebase Cloud Messaging and platform-dependent GNOME, DBus,
GLib, macOS and Windows desktop notifications. Some optional features of listed
providers, such as encrypted Bark payloads or PGP email, also need extra packages.

Diese optionalen Anbieter und Zusatzfunktionen gehören wie bisher **nicht zum
Basispaket**. Die Anzahl verfügbarer Anbieter ist keine Zusicherung, dass alle
optionalen Funktionen eines Anbieters ohne weitere Abhängigkeiten verfügbar sind.

Apprise 2 validates URL options more strictly. Legacy PGP email options
`use_pgp` / `pgpkey` were replaced by `pgp_mode` / `pgppub`; PGP dependencies
remain optional and are not bundled. No saved URLs or credentials are rewritten.
For ntfy with an explicit host, `ntfy://` uses HTTP and `ntfys://` uses HTTPS,
just as before. For token-authenticated ntfy.sh use
`ntfys://{token}@ntfy.sh/{topic}` with your `tk_` token; do not post real tokens
in logs or support requests.

Apprise 2 prüft URL-Optionen strenger. Die bisherigen PGP-Mail-Optionen
`use_pgp` / `pgpkey` wurden durch `pgp_mode` / `pgppub` ersetzt; die optionalen
PGP-Abhängigkeiten sind weiterhin nicht enthalten. Gespeicherte URLs und
Zugangsdaten werden nicht automatisch verändert. Bei ntfy mit explizitem Host
steht `ntfy://` wie bisher für HTTP und `ntfys://` für HTTPS. Für ntfy.sh mit
Token verwenden Sie `ntfys://{token}@ntfy.sh/{topic}` mit Ihrem `tk_`-Token.
Echte Tokens gehören nicht in Logs oder Support-Anfragen.

Source / Quelle: runtime discovery against the hash-pinned bundle; version-bound
inventory in `plugin/apprise-providers.json`. No external service credentials are
used to produce this inventory. Compatibility changes: upstream releases
[v2.0.0](https://github.com/caronc/apprise/releases/tag/v2.0.0) and
[v2.1.0](https://github.com/caronc/apprise/releases/tag/v2.1.0).

| Provider / Anbieter | URL schemes / URL-Schemata |
| --- | --- |
| 46elks | `46elks://`, `elks://` |
| 800.com | `eight00com://` |
| Africas Talking | `atalk://` |
| AMQP | `amqp://`, `amqps://` |
| Apprise API | `apprise://`, `apprises://` |
| Aprs | `aprs://` |
| AWS Simple Email Service (SES) | `ses://` |
| AWS Simple Notification Service (SNS) | `sns://` |
| Bark | `bark://`, `barks://` |
| Better Stack | `betterstack://` |
| BlueSky | `bluesky://`, `bsky://` |
| Brevo | `brevo://` |
| BulkSMS | `bulksms://` |
| BulkVS | `bulkvs://` |
| Burst SMS | `burstsms://` |
| Chanify | `chanify://` |
| Cisco Webex Teams | `webex://`, `wxteams://` |
| Clickatell | `clickatell://` |
| ClickSend | `clicksend://` |
| D7 Networks | `d7sms://` |
| Dapnet | `dapnet://` |
| Delta Chat | `deltachat://`, `deltachats://` |
| DingTalk | `dingtalk://` |
| Discord | `discord://` |
| Dot. | `dot://` |
| E-Mail | `mailto://`, `mailtos://` |
| Emby | `emby://`, `embys://` |
| Enigma2 | `enigma2://`, `enigma2s://` |
| Evolution API | `evolution://`, `evolutions://` |
| Exotel | `exotel://` |
| Feishu | `feishu://` |
| Flock | `flock://` |
| Flowtriq | `flowtriq://`, `flowtriqs://` |
| Fluxer | `fluxer://`, `fluxers://` |
| Form | `form://`, `forms://` |
| Free-Mobile | `freemobile://` |
| GitHub | `github://` |
| GoAlert | `goalert://`, `goalerts://` |
| Google Chat | `gchat://` |
| Gorush | `gorush://`, `gorushs://` |
| Gotify | `gotify://`, `gotifys://` |
| GroupMe | `groupme://` |
| Guilded | `guilded://` |
| HomeAssistant | `hassio://`, `hassios://` |
| httpSMS | `httpsms://` |
| HumHub | `humhub://`, `humhubs://` |
| IFTTT | `ifttt://` |
| ilert | `ilert://` |
| incident.io | `incidentio://` |
| IRC | `irc://`, `ircs://` |
| Jellyfin | `jellyfin://`, `jellyfins://` |
| Jira | `jira://` |
| Join | `join://` |
| JSON | `json://`, `jsons://` |
| Kavenegar | `kavenegar://` |
| Kodi/XBMC | `kodi://`, `kodis://`, `xbmc://`, `xbmcs://` |
| Kook | `kook://` |
| Kumulos | `kumulos://` |
| LaMetric | `lametric://`, `lametrics://` |
| Lark (Feishu) | `lark://` |
| Lauther | `lauther://` |
| LFG Alarm | `lfg://` |
| Line | `line://` |
| MailerSend | `mailersend://` |
| Mailgun | `mailgun://` |
| Mastodon | `mastodon://`, `mastodons://`, `toot://`, `toots://` |
| Matrix | `matrix://`, `matrixs://` |
| Mattermost | `mmost://`, `mmosts://` |
| MessageBird | `msgbird://` |
| Misskey | `misskey://`, `misskeys://` |
| Mobile Message | `mobilemessage://`, `mobilemsg://` |
| MSG91 | `msg91://` |
| Nextcloud | `ncloud://`, `nclouds://` |
| Nextcloud Talk | `nctalk://`, `nctalks://` |
| Notica | `notica://`, `noticas://` |
| Notifiarr | `notifiarr://` |
| Notifico | `notifico://`, `notificos://` |
| Notifyre | `notifyre://` |
| ntfy | `ntfy://`, `ntfys://` |
| Octopush | `octopush://` |
| Office 365 | `azure://`, `o365://` |
| OneBot | `onebot://`, `onebots://` |
| OneSignal | `onesignal://` |
| Opsgenie | `opsgenie://` |
| Pager Duty | `pagerduty://` |
| PagerTree | `pagertree://` |
| Parse Platform | `parsep://`, `parseps://` |
| Pinglet | `pinglet://`, `pinglets://` |
| Pingram | `pingram://` |
| Plivo | `plivo://` |
| Postmark | `postmark://` |
| Power Automate / Workflows (for MSTeams) | `workflow://`, `workflows://` |
| Prowl | `prowl://` |
| Pushbullet | `pbul://` |
| PushDeer | `pushdeer://`, `pushdeers://` |
| Pushed | `pushed://` |
| Pushjet | `pjet://`, `pjets://` |
| PushMe | `pushme://` |
| Pushover | `pover://` |
| Pushplus | `pushplus://`, `wecom://` |
| Pushsafer | `psafer://`, `psafers://` |
| PushWard | `pushward://` |
| Pushy | `pushy://` |
| QQ Push | `qq://` |
| Reddit | `reddit://` |
| Remote Syslog | `rsyslog://` |
| Resend | `resend://` |
| Revolt | `revolt://` |
| RingCentral | `ringc://` |
| Rocket.Chat | `rocket://`, `rockets://` |
| Ryver | `ryver://` |
| SendGrid | `sendgrid://` |
| SendPulse | `sendpulse://` |
| ServerChan | `schan://` |
| SerwerSMS | `serwersms://` |
| seven | `seven://` |
| Signal API | `signal://`, `signals://` |
| Signalgrid | `signalgrid://` |
| SIGNL4 | `signl4://` |
| Simplepush | `simplepush://`, `spush://` |
| Sinch | `sinch://` |
| Slack | `slack://` |
| SMS Eagle | `smseagle://`, `smseagles://` |
| SMS Manager | `smsmanager://`, `smsmgr://` |
| SMSC | `smsc://` |
| SMTP2Go | `smtp2go://` |
| Société Française du Radiotéléphone | `sfr://` |
| SparkPost | `sparkpost://` |
| Spike.sh | `spike://` |
| Splunk On-Call | `splunk://`, `victorops://` |
| SpugPush | `spugpush://` |
| Squadcast | `squadcast://` |
| Stackfield | `stackfield://` |
| Streamlabs | `strmlabs://` |
| Synology Chat | `synology://`, `synologys://` |
| Syslog | `syslog://` |
| Techulus Push | `push://` |
| Telegram | `tgram://` |
| Telnyx | `telnyx://` |
| Threema Gateway | `threema://` |
| Trigv | `trigv://`, `trigvs://` |
| Twilio | `twilio://` |
| Twist | `twist://` |
| Twitter | `tweet://`, `twitter://`, `x://` |
| Viber | `viber://` |
| VoIPms | `voipms://` |
| Vonage | `nexmo://`, `vonage://` |
| WeChat (WeCom) | `wechat://` |
| WeCom Bot | `wecombot://` |
| WhatsApp | `whatsapp://` |
| WPUSH | `wpush://` |
| WxPusher | `wxpusher://` |
| XML | `xml://`, `xmls://` |
| YouLMK | `youlmk://` |
| Zalo | `zalo://` |
| Zoho Cliq | `cliq://`, `zcliq://`, `zohocliq://` |
| Zoom | `zoom://` |
| Zulip | `zulip://` |
