scalable_dir = 'hicolor' / 'scalable' / 'apps'
install_data(
  scalable_dir / f'@app_id@.svg',
  install_dir: get_option('datadir') / 'icons' / scalable_dir,
)

symbolic_dir = 'hicolor' / 'symbolic' / 'apps'
install_data(
  symbolic_dir / f'@app_id@-symbolic.svg',
  install_dir: get_option('datadir') / 'icons' / symbolic_dir,
)

subdir('scalable/actions')
