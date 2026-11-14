.pragma library

function source(url, naturalSizeRequest) {
    if (/^file:\/\/.*\.svgz?(?:$|[?#])/i.test(url))
        return "image://vectors/" + (naturalSizeRequest ? "natural/" + naturalSizeRequest.width + "/" : "") + encodeURIComponent(url)
    return url
}
