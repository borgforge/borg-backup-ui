<?PHP
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');

$cache_file = '/boot/config/plugins/borg-backup-ui/widget-status.json';

if (!is_file($cache_file)) {
  http_response_code(404);
  echo json_encode([
    'ok' => false,
    'error' => 'missing',
  ]);
  exit;
}

$raw = file_get_contents($cache_file);
$decoded = json_decode($raw, true);
if (!is_array($decoded)) {
  http_response_code(500);
  echo json_encode([
    'ok' => false,
    'error' => 'invalid',
  ]);
  exit;
}

echo json_encode($decoded, JSON_UNESCAPED_SLASHES);
?>
