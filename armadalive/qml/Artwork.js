.pragma library

function source(url) {
    if (/^file:\/\/.*\.svgz?(?:$|[?#])/i.test(url))
        return "image://vectors/" + encodeURIComponent(url)
    return url
}
