#!/usr/bin/env perl
use strict;
use warnings;

# Stream Docker log lines without changing their timestamp prefix.  Only
# credential-like values are replaced; variable names and the rest of each
# line remain available for later correlation.
$| = 1;
while (my $line = <STDIN>) {
    $line =~ s{((?:Authorization:\s*Bearer|Bearer)\s+)[^\s,;]+}{${1}[REDACTED]}ig;
    $line =~ s{((?:x[-_]?(?:api[-_]?key|auth[-_]?token)|api[_-]?key|token|password|secret|client[_-]?secret|access[_-]?key|gateway[_-]?key|matrix[_-]?token|registration[_-]?token|license[_-]?key)\s*[=:]\s*)(?:"[^"]*"|'[^']*'|[^\s,;]+)}{${1}[REDACTED]}ig;
    $line =~ s{((?:AGENTTEAMS|NACOS|SKILLS)_[A-Z0-9_]*(?:TOKEN|PASSWORD|SECRET|KEY|COOKIE)[A-Z0-9_]*\s*[=:]\s*)(?:"[^"]*"|'[^']*'|[^\s,;]+)}{${1}[REDACTED]}ig;
    $line =~ s{((?:https?|nacos)://)[^\/\s:@]+:[^\/\s@]+\@}{${1}[REDACTED]\@}ig;
    print $line;
}
