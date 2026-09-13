# Apprise 1.13.1 providers / Anbieter (#269)

This package exposes **141 providers** through Settings > Notifications. The
existing base-package strategy is retained; optional dependencies from
`all-plugins` are not added. Search by provider name or URL scheme to select a
provider. The generic URL entry remains available.

Dieses Paket bietet **141 Anbieter** unter Einstellungen > Benachrichtigungen.
Die bisherige Paketstrategie bleibt bestehen; optionale Abhängigkeiten aus
`all-plugins` werden nicht ergänzt. Suche nach Anbietername oder URL-Schema,
um einen Anbieter auszuwählen. Die generische URL-Eingabe bleibt verfügbar.

New / Neu: **Pinglet, Trigv, Pingram, Signalgrid, Lauther**.

Removed / Entfallen: **NotificationAPI** (`napi://`, `notificationapi://`).
Reconfigure affected profiles with new Pingram credentials or another provider.
Betroffene Profile mit neuen Pingram-Zugangsdaten oder einem anderen Anbieter
neu einrichten. Gespeicherte Einstellungen und Secrets bleiben erhalten.

The following providers are **not available in the base bundle**, as before:
MQTT, XMPP, Growl, SMPP, blink(1), SimplePush, Session Open Group Server,
Vapid Web Push, Firebase Cloud Messaging and platform-dependent GNOME, DBus,
GLib, macOS and Windows desktop notifications. Some optional features of listed
providers, such as encrypted Bark payloads or PGP email, also need extra packages.

Diese optionalen Anbieter und Zusatzfunktionen gehören wie bisher **nicht zum
Basispaket**. Die Anzahl verfügbarer Anbieter ist keine Zusicherung, dass alle
optionalen Funktionen eines Anbieters ohne weitere Abhängigkeiten verfügbar sind.

Source / Quelle: runtime discovery against the hash-pinned bundle; version-bound
inventory in `plugin/apprise-providers.json`. No external service credentials are
used to produce this inventory.

| Provider / Anbieter | URL schemes / URL-Schemata |
| --- | --- |
| 46elks | `46elks://`, `elks://` |
| 800.com | `eight00com://` |
| Africas Talking | `atalk://` |
| Amazon Chime | `chime://` |
| Apprise API | `apprise://`, `apprises://` |
| Aprs | `aprs://` |
| AWS Simple Email Service (SES) | `ses://` |
| AWS Simple Notification Service (SNS) | `sns://` |
| Bark | `bark://`, `barks://` |
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
| Google Chat | `gchat://` |
| Gotify | `gotify://`, `gotifys://` |
| GroupMe | `groupme://` |
| Guilded | `guilded://` |
| HomeAssistant | `hassio://`, `hassios://` |
| httpSMS | `httpsms://` |
| HumHub | `humhub://`, `humhubs://` |
| IFTTT | `ifttt://` |
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
| Line | `line://` |
| MailerSend | `mailersend://` |
| Mailgun | `mailgun://` |
| Mastodon | `mastodon://`, `mastodons://`, `toot://`, `toots://` |
| Matrix | `matrix://`, `matrixs://` |
| Mattermost | `mmost://`, `mmosts://` |
| MessageBird | `msgbird://` |
| Misskey | `misskey://`, `misskeys://` |
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
| Stackfield | `stackfield://` |
| Streamlabs | `strmlabs://` |
| Synology Chat | `synology://`, `synologys://` |
| Syslog | `syslog://` |
| Techulus Push | `push://` |
| Telegram | `tgram://` |
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
| WxPusher | `wxpusher://` |
| XML | `xml://`, `xmls://` |
| Zoom | `zoom://` |
| Zulip | `zulip://` |
