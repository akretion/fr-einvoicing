-- Crons are not switched off here: base's neutralize.sql already
-- deactivates every cron but the autovacuum.

-- remove access/refresh tokens: with the authorization_code method the
-- access to the accredited platform lives here, not in res_company
DELETE FROM fr_einvoicing_token;

-- remove credentials and authentication method, and stop sending
-- customer invoices and getting vendor bills through the platform
UPDATE res_company
   SET fr_ctc_auth_method = NULL,
       fr_ctc_client_id = NULL,
       fr_ctc_client_secret = NULL,
       fr_ctc_send_out_invoice = 'none',
       fr_ctc_get_in_invoice = false;

-- without credentials the directory query fails: keep invoices postable
UPDATE res_company
   SET fr_ctc_directory_sync_on_invoice_post = 'not_blocking'
 WHERE fr_ctc_directory_sync_on_invoice_post = 'blocking';
