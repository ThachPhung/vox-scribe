//! Lưu file ghi âm của cuộc họp ra chỗ người dùng chọn qua hộp thoại "Lưu thành…" của Windows.
//!
//! WebView của Tauri không xử lý link tải về như trình duyệt, nên giao diện gọi lệnh này.
//! Chỉ chép file .wav có thật; nơi lưu do người dùng chọn trong hộp thoại, không nhận từ giao diện.

use std::path::{Path, PathBuf};

use tauri_plugin_dialog::DialogExt;

/// Mở hộp thoại lưu và chép `source` (file WAV của cuộc họp) tới đó.
/// Trả về đường dẫn đã lưu, hoặc `None` nếu người dùng bấm Huỷ.
#[tauri::command]
pub async fn save_recording(
  app: tauri::AppHandle,
  source: String,
  suggested_name: String,
) -> Result<Option<String>, String> {
  let source = PathBuf::from(source);
  validate_source(&source)?;

  // Lệnh async chạy ngoài luồng giao diện, nên dùng bản blocking của hộp thoại được.
  let picked = app
    .dialog()
    .file()
    .set_title("Lưu file ghi âm")
    .set_file_name(safe_file_name(&suggested_name))
    .add_filter("Âm thanh WAV", &["wav"])
    .blocking_save_file();
  let Some(target) = picked else {
    return Ok(None);
  };
  let target = target.into_path().map_err(|e| format!("Đường dẫn lưu không hợp lệ: {e}"))?;
  let target = with_wav_extension(target);

  std::fs::copy(&source, &target).map_err(|e| format!("Không lưu được file: {e}"))?;
  Ok(Some(target.display().to_string()))
}

fn validate_source(source: &Path) -> Result<(), String> {
  let is_wav = source
    .extension()
    .is_some_and(|ext| ext.eq_ignore_ascii_case("wav"));
  if !is_wav {
    return Err("Chỉ lưu được file ghi âm .wav".into());
  }
  if !source.is_file() {
    return Err("Không còn file ghi âm của cuộc họp này".into());
  }
  Ok(())
}

/// Bỏ ký tự Windows không cho dùng trong tên file và bảo đảm đuôi .wav.
fn safe_file_name(name: &str) -> String {
  let cleaned: String = name
    .chars()
    .map(|c| if "<>:\"/\\|?*".contains(c) || c.is_control() { '-' } else { c })
    .collect();
  let cleaned = cleaned.trim_matches(|c: char| c == ' ' || c == '.');
  let base = if cleaned.is_empty() { "cuoc-hop" } else { cleaned };
  if base.to_lowercase().ends_with(".wav") {
    base.to_string()
  } else {
    format!("{base}.wav")
  }
}

fn with_wav_extension(path: PathBuf) -> PathBuf {
  let has_wav = path
    .extension()
    .is_some_and(|ext| ext.eq_ignore_ascii_case("wav"));
  if has_wav { path } else { path.with_extension("wav") }
}

#[cfg(test)]
mod tests {
  use super::*;

  #[test]
  fn safe_file_name_replaces_windows_reserved_chars() {
    assert_eq!(safe_file_name("Cuộc họp 12/11 06:58"), "Cuộc họp 12-11 06-58.wav");
    assert_eq!(safe_file_name("  ...  "), "cuoc-hop.wav");
    assert_eq!(safe_file_name("họp.WAV"), "họp.WAV");
  }

  #[test]
  fn validate_source_rejects_non_wav_and_missing_files() {
    assert!(validate_source(Path::new("C:/Windows/win.ini")).is_err());
    assert!(validate_source(Path::new("C:/khong-co/file.wav")).is_err());
  }

  #[test]
  fn with_wav_extension_adds_missing_extension() {
    assert_eq!(with_wav_extension(PathBuf::from("a/b")), PathBuf::from("a/b.wav"));
    assert_eq!(with_wav_extension(PathBuf::from("a/b.WAV")), PathBuf::from("a/b.WAV"));
  }
}
