# A Markdown table of a once-campfire-verification benchmark's results:
# the median req/s of each route over the rounds, per app.
#   ruby script/bench_summary.rb RESULTS_DIR
require "json"
dir = ARGV.fetch(0)
rows = Dir[File.join(dir, "*-[0-9]*.json")].map { |f| JSON.parse(File.read(f)) }.select { |r| r["http"] }
abort "no results in #{dir}" if rows.empty?
apps = rows.map { |r| r["app"] }.uniq
routes = rows.flat_map { |r| r["http"].map { |h| h["route"] } }.uniq
median = ->(xs) { s = xs.sort; s.size.odd? ? s[s.size / 2] : (s[s.size / 2 - 1] + s[s.size / 2]) / 2.0 }
puts "| route | #{apps.join(' | ')} |"
puts "| --- |#{' ---: |' * apps.size}"
routes.each do |route|
  cells = apps.map do |app|
    rps = rows.select { |r| r["app"] == app }.flat_map { |r| r["http"] }.select { |h| h["route"] == route && h["conc"] == 16 }.map { |h| h["rps"] }
    rps.empty? ? "" : format("%.0f", median.(rps))
  end
  puts "| #{route} | #{cells.join(' | ')} |"
end
puts
puts "Median requests/second over #{rows.map { |r| r["round"] || 0 }.max} round(s), 16 clients."
