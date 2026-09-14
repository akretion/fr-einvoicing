import setuptools

with open('VERSION.txt', 'r') as f:
    version = f.read().strip()

setuptools.setup(
    name="odoo-addons-akretion-fr-einvoicing",
    description="Meta package for akretion-fr-einvoicing Odoo addons",
    version=version,
    install_requires=[
        'odoo-addon-account_invoice_en16931>=16.0dev,<16.1dev',
        'odoo-addon-account_invoice_en16931_py3o>=16.0dev,<16.1dev',
        'odoo-addon-l10n_fr_account_invoice_en16931>=16.0dev,<16.1dev',
        'odoo-addon-l10n_fr_einvoicing>=16.0dev,<16.1dev',
        'odoo-addon-l10n_fr_einvoicing_dashboard_banner>=16.0dev,<16.1dev',
        'odoo-addon-l10n_fr_einvoicing_directory_import>=16.0dev,<16.1dev',
        'odoo-addon-l10n_fr_einvoicing_import>=16.0dev,<16.1dev',
        'odoo-addon-l10n_fr_einvoicing_purchase>=16.0dev,<16.1dev',
        'odoo-addon-l10n_fr_einvoicing_sale>=16.0dev,<16.1dev',
    ],
    classifiers=[
        'Programming Language :: Python',
        'Framework :: Odoo',
        'Framework :: Odoo :: 16.0',
    ]
)
