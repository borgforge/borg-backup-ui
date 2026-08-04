<?PHP
$PLUGIN_DIR = "/boot/config/plugins/borg-backup-ui";

function bbui_json_response($payload) {
  header('Content-Type: application/json');
  header('Cache-Control: no-store');
  echo json_encode($payload);
  exit;
}

function bbui_request_value($key, $default = '') {
  static $raw_post = null;
  if (isset($_POST[$key])) return $_POST[$key];
  if ($raw_post === null) {
    $raw_post = [];
    $raw = file_get_contents('php://input');
    if (is_string($raw) && $raw !== '') {
      parse_str($raw, $raw_post);
    }
  }
  return $raw_post[$key] ?? $default;
}

function bbui_python_runtime_status() {
  $path = trim((string)shell_exec("command -v python3 2>/dev/null"));
  if ($path === '' || !is_executable($path)) {
    return ['ok' => false, 'path' => '', 'reason' => 'Python 3 is not available. Install or update Python 3 for Unraid first.'];
  }
  $cmd = escapeshellarg($path) . " -c " . escapeshellarg("import sys; print('.'.join(map(str, sys.version_info[:3]))); raise SystemExit(0 if sys.version_info >= (3, 10) else 1)") . " 2>/dev/null";
  $lines = [];
  $rc = 1;
  exec($cmd, $lines, $rc);
  $version = trim((string)($lines[0] ?? ''));
  if ($version === '') {
    return ['ok' => false, 'path' => $path, 'reason' => 'The Python version could not be determined.'];
  }
  if ($rc !== 0) {
    return ['ok' => false, 'path' => $path, 'reason' => "Python $version is too old. Python 3.10 or newer is required."];
  }
  return ['ok' => true, 'path' => $path, 'version' => $version, 'reason' => ''];
}

function bbui_run_admin_recovery($plugin_dir, $python_path, $username, $password) {
  $script = "$plugin_dir/api/admin_recovery.py";
  if (!is_file($script)) {
    return ['ok' => false, 'error' => 'Admin recovery helper is missing. Reinstall or update the plugin package.'];
  }

  $cmd = escapeshellarg($python_path) . ' ' . escapeshellarg($script) . ' --control-page';
  $descriptors = [
    0 => ['pipe', 'r'],
    1 => ['pipe', 'w'],
    2 => ['pipe', 'w'],
  ];
  $env = $_ENV;
  $env['BBUI_PLUGIN_DIR'] = $plugin_dir;
  $process = proc_open($cmd, $descriptors, $pipes, null, $env);
  if (!is_resource($process)) {
    return ['ok' => false, 'error' => 'Admin recovery could not be started.'];
  }

  fwrite($pipes[0], json_encode(['username' => $username, 'password' => $password]));
  fclose($pipes[0]);
  $stdout = stream_get_contents($pipes[1]);
  fclose($pipes[1]);
  stream_get_contents($pipes[2]);
  fclose($pipes[2]);
  $rc = proc_close($process);
  $result = json_decode($stdout, true);
  if (!is_array($result)) {
    return ['ok' => false, 'error' => 'Admin recovery returned an invalid response.'];
  }
  if ($rc !== 0 || empty($result['ok'])) {
    return ['ok' => false, 'error' => (string)($result['error'] ?? 'Admin recovery failed.')];
  }
  return $result;
}

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
  bbui_json_response(['ok' => false, 'error' => 'Admin recovery requires POST.']);
}

$username = trim((string)bbui_request_value('username', ''));
$password = (string)bbui_request_value('password', '');
$password_confirm = (string)bbui_request_value('password_confirm', '');

if ($password !== $password_confirm) {
  bbui_json_response(['ok' => false, 'error' => 'The password confirmation does not match.']);
}

$python = bbui_python_runtime_status();
if (empty($python['ok'])) {
  bbui_json_response(['ok' => false, 'error' => (string)($python['reason'] ?? 'Python 3 is not available.')]);
}

bbui_json_response(bbui_run_admin_recovery($PLUGIN_DIR, $python['path'], $username, $password));
