-- Turnover read from a PDF as zero or negative is a misread (turnover is never
-- negative): clear it so the estimate is used instead. Filed-as-data figures are untouched.
update financial_period set turnover = null
where source like 'pdf:%' and turnover is not null and turnover <= 0;
