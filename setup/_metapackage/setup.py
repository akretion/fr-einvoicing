import setuptools

with open('VERSION.txt', 'r') as f:
    version = f.read().strip()

setuptools.setup(
    name="odoo14-addons-akretion-fr-einvoicing",
    description="Meta package for akretion-fr-einvoicing Odoo addons",
    version=version,
    install_requires=[
        'odoo14-addon-l10n_fr_einvoicing_onboarding',
    ],
    classifiers=[
        'Programming Language :: Python',
        'Framework :: Odoo',
        'Framework :: Odoo :: 14.0',
    ]
)
