project(
    'openemail',
    version: '0.1.0',
    meson_version: '>= 1.0.0',
    default_options: ['warning_level=2', 'werror=false'],
)

dependency('gtk4', version: '>= 4.18.0')
dependency('libadwaita-1', version: '>= 1.7')

i18n = import('i18n')
gnome = import('gnome')
python = import('python')

py_installation = python.find_installation('python3')

pkgdatadir = get_option('prefix') / get_option('datadir') / meson.project_name()
localedir = get_option('prefix') / get_option('localedir')
bindir = get_option('bindir')

profile = 'release'
app_id = 'com.mercata.OpenEmail'
prefix = '/com/mercata/OpenEmail'

conf = configuration_data(
    {
        'PYTHON': py_installation.full_path(),
        'APP_ID': app_id,
        'VERSION': meson.project_version(),
        'PREFIX': prefix,
        'PROFILE': profile,
        'PKGDATADIR': pkgdatadir,
        'LOCALEDIR': localedir,
        'BINDIR': bindir,
    },
)

subdir('data')
subdir('openemail')
subdir('po')

gnome.post_install(
    glib_compile_schemas: true,
    gtk_update_icon_cache: true,
    update_desktop_database: true,
)
