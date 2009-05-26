#!/usr/local/bin/python -u

import cgi
import os.path
import pickle
from random import choice, randint
import sys
import traceback

#from urllib.error import URLError
#from urllib.parse import urlencode
#from urllib.request import urlopen
from urllib import urlopen, urlencode, urlretrieve
from xml.dom.minidom import parse

from PIL import Image
from PIL import ImageFont, ImageDraw

"""I'm on a boat."""


_DEBUG = False

_default_flickr_params = {'api_key': 'eb15a53de972a6af01ba2922ffa3339e',
        'panda_name': 'wang wang',
        'per_page': '1'}
_default_meme_params = {}
_cachedirname = '/tmp'
_savedfilesdirname = 'saved'
_pandacachebasename = 'vomit.pcl'
_memecachebasename = 'beer.pcl'
_topthreshhold = 200
_bottomthreshhold = 20

_photo_url_tmpl = 'http://farm%s.static.flickr.com/%s/%s_%s.jpg'


class TryAgain(Exception):
    pass


class BlowUpTheWorldAndRestart(Exception):
    pass


#def notify(*args, **kwargs):
#    print(*args, file=sys.stderr, **kwargs)
def notify(s):
    if _DEBUG:
        sys.stderr.write(s)


def getflickrurl(params):
    return ('http://api.flickr.com/services/rest/?'
            'method=flickr.panda.getPhotos&%s' % urlencode(params))


def getmemeurl(params):
    return 'http://meme.boxofjunk.ws/moar.txt'


def constructphotourl(photo_dom):
    farm_id = photo_dom.getAttribute('farm')
    server_id = photo_dom.getAttribute('server')
    photo_id = photo_dom.getAttribute('id')
    secret = photo_dom.getAttribute('secret')
    return _photo_url_tmpl % (farm_id, server_id, photo_id, secret)


def chew(dom):
    rsp = dom.getElementsByTagName('rsp')[0]
    if rsp.getAttribute('stat') != 'ok':
        raise Exception('request failed, sorry')
    photos = rsp.getElementsByTagName('photos')[0]
    timestamp = photos.getAttribute('lastupdate')
    photolist = photos.getElementsByTagName('photo')
    return timestamp, [constructphotourl(p) for p in photolist]


def _getcachefilename(cachebasename):
    return os.path.join(_cachedirname, cachebasename)


def killcache(cachebasename):
    cachefilename = _getcachefilename(cachebasename)
    if os.path.exists(cachefilename):
        os.unlink(cachefilename)


def loadcache(cachebasename):
    cachefilename = _getcachefilename(cachebasename)
    if os.path.exists(cachefilename):
        try:
            cachefile = open(cachefilename, 'rb')
        except IOError, e:
            raise e
        else:
            return pickle.load(cachefile)
    return []


def savecache(cachebasename, cache):
    cachefilename = _getcachefilename(cachebasename)
    if os.path.exists(cachefilename):
        os.unlink(cachefilename)
    # CRITICAL SECTION OH NOES
    try:
        cachefile = open(cachefilename, 'wb')
    except IOError, e:
        raise e
    else:
        pickle.dump(cache[-_topthreshhold:], cachefile)


def loadflickrdata():
    flickr_params = _default_flickr_params

    notify('Loading Flickr cache...')
    tpl = loadcache(_pandacachebasename)
    if tpl:
        vomitfreesince, pandacache = tpl
    else:
        vomitfreesince, pandacache = ('', [])
    notify('done!\nLoaded %d urls.\n' % len(pandacache))
    if len(pandacache) < _bottomthreshhold:
        notify('Loading new Flickr data...')
        try:
            xmldata = urlopen(getflickrurl(flickr_params))
        except IOError, e:
            raise e
        else:
            notify('done!\n')
            dom = parse(xmldata)
            lastupdate, newphotolist = chew(dom)
            if vomitfreesince != lastupdate:
                notify('Got %d new images.\n' % len(newphotolist))
                vomitfreesince = lastupdate
                pandacache.extend(newphotolist)
            else:
                notify('No new images.\n')
    else:
        notify('Got enough images for now.\n')

    return vomitfreesince, pandacache


def loadmemedata(pandacache):
    meme_params = _default_meme_params

    notify('Loading meme cache...')
    memecache = loadcache(_memecachebasename)
    notify('done!\nLoaded %d memes.\n' % len(memecache))
    if len(memecache) < _bottomthreshhold:
        notify('Loading new meme data...')
        try:
            data = urlopen(getmemeurl(meme_params))
        except IOError, e:
            raise e
        else:
            notify('done!\n')
            newmemelist = data.read().rstrip().split("\n")
            notify('Got %d new memes.\n' % len(newmemelist))
            memecache.extend(newmemelist)
    else:
        notify('Got enough memes for now.\n')

    return memecache


def getimage(url):
    try:
        (filename, _) = urlretrieve(url)
    except IOError, e:
        raise e
    else:
        image = Image.open(filename)
        image.load()
        return image, filename


def getfont():
    fontpath = os.path.join('/home/leif/webapps/memeshup', 'Arial_Black.ttf')
    return ImageFont.truetype(fontpath, 36)


def _possiblesplits(text, alreadysplit):
    # the following is a super fucking ugly recursive generator
    # shut your mouth, it's late
    words = text.split()
    if len(words) == 1:
        yield text
    else:
        for i in range(1, len(words)):
            lhs = ' '.join(words[:i])
            rhs = ' '.join(words[i:])
            if rhs in alreadysplit:
                for rhssplit in alreadysplit[rhs]:
                    yield '%s %s' % (lhs, rhssplit)
                    yield '%s\n%s' % (lhs, rhssplit)
            else:
                rhssplits = set()
                for rhssplit in _possiblesplits(rhs, alreadysplit):
                    yield '%s %s' % (lhs, rhssplit)
                    yield '%s\n%s' % (lhs, rhssplit)
                    rhssplits.add(rhssplit)
                alreadysplit[rhs] = rhssplits


def possiblesplits(text):
    # also a dirty hack
    splits = set()
    alreadysplit = {}
    for split in _possiblesplits(text, alreadysplit):
        splits.add(split)
    del alreadysplit
    return list(splits)


def boundingbox(text, draw, font):
    width = height = 0
    for line in text.split("\n"):
        size = draw.textsize(line, font=font)
        width = max(width, size[0])
        height += size[1]
    return width, height


def fitsinimage(text, image, draw, font):
    width, height = boundingbox(text, draw, font)
    return (width <= (image.size[0] - 20)) and (height <= (image.size[1] - 20))


def areaofsplit(text, draw, font):
    #sum = 0
    #for line in text.split("\n"):
    #    size = draw.textsize(line, font=font)
    #    sum += size[0] * size[1]
    #    sum += 3000  # tune this
    #return sum
    bb = boundingbox(text, draw, font)
    return bb[0] * bb[1]


def minkey(lst, key=None):
    m = None
    for elt in lst:
        if key is None:
            if m is None or elt < m:
                m = elt
        else:
            if m is None or key(elt) < key(m):
                m = elt
    return m


def choosetext(text, image, draw, font):
    if len(text.split()) > 10:
        raise TryAgain('Text is too long.  Try again.')

    possibletexts = (t for t in possiblesplits(text)
            if fitsinimage(t, image, draw, font))

    if not possibletexts:
        raise TryAgain("Can't fit text in this image.  Try again.")

    def _areakey(text):
        # close over font
        return areaofsplit(text, draw, font)

    return minkey(possibletexts, key=_areakey)


def chooseposition(image, bb):
    top = randint(0, 1) == 1
    left = randint(0, 1) == 1

    if top:
        notify('Going for top.\n')
        ypos = 10
    else:
        notify('Going for bottom.\n')
        ypos = image.size[1] - 10 - bb[1]
    if left:
        notify('Going for left.\n')
        xpos = 10
    else:
        notify('Going for right.\n')
        xpos = image.size[0] - 10 - bb[0]

    return xpos, ypos


#def draw_text(draw, text, font, bb, xpos, ypos, fill=(255, 255, 255),
#            outline=(0, 0, 0)):
def draw_text(draw, text, font, bb, xpos, ypos, fill=(255, 255, 255)):
    for line in text.split("\n"):
        size = draw.textsize(line, font=font)

        lalign = xpos == 10  #True  #randint(0, 3) == 0
        if lalign:
            xadd = 0
        else:
            xadd = bb[0] - size[0]

        #draw.text((xpos + xadd, ypos), line, font=font, fill=fill,
        #        outline=outline)
        try:
            draw.text((xpos + xadd, ypos), line, font=font, fill=fill)
        except ValueError, e:
            raise BlowUpTheWorldAndRestart

        ypos += size[1]


def getfill(image):
    hist = image.histogram()

    # Explanation:
    # For each color, take the bottom and top 96 intensities.  If the bottom
    # intensities are more common than the top intensities, pick intensity 255,
    # else 0.  Combine each color to get one of black, white, red, green, blue,
    # yellow, magenta, or cyan.
    if sum(hist[:96]) - sum(hist[160:256]) > 0:
        red = 255
    else:
        red = 0
    if sum(hist[256:352]) - sum(hist[416:512]) > 0:
        green = 255
    else:
        green = 0
    if sum(hist[512:608]) - sum(hist[672:768]) > 0:
        blue = 255
    else:
        blue = 0
    
    notify('Choosing colour (%d, %d, %d)\n' % (red, green, blue))
    return (red, green, blue)
    #return (255, 255, 255)


def get_outline(image):
    return (0, 0, 0)


def superimpose(text, image):
    draw = ImageDraw.Draw(image)
    font = getfont()

    chosentext = choosetext(text, image, draw, font)

    if not chosentext:
        raise TryAgain('Should have already raised this...')

    bb = boundingbox(chosentext, draw, font)

    notify('Bounding Box is (%d, %d)\n' % bb)

    xpos, ypos = chooseposition(image, bb)

    notify('Position is (%d, %d)\n' % (xpos, ypos))

    fill = getfill(image)
    #outline = get_outline(image)

    #notify('Chose fill=%s, outline=%s\n' % (fill, outline))

    #draw_text(draw, chosentext, font, bb, xpos, ypos, fill=fill,
    #         outline=outline)
    draw_text(draw, chosentext, font, bb, xpos, ypos, fill=fill)

    return image


def cleantempimages():
    def visit(arg, dirname, names):
        for name in names:
            if name[-4:] == '.jpg':
                os.unlink(name)
    os.path.walk('.', visit, None)


def do_output(image, filename):
    print('Content-Type: text/html\n\n')
    image.save(filename, 'JPEG')
    if not os.path.exists(filename):
        raise Exception('Failed to save image.')
    try:
        html = open('index.html.tmpl', 'r')
    except IOError, e:
        raise e
    else:
        for line in html.readlines():
            idx = line.find('@FILENAME@')
            if idx != -1:
                line = line[:idx] + filename + line[idx+10:]
            print(line)


def do_save(form):
    filename = form.getvalue('filename')

    cwd = os.getcwd()
    if (cwd != os.path.dirname(os.path.abspath(filename)) or
            not filename.endswith('.jpg')):
        raise Exception('Someone is trying to hack in.  I see you!')

    savename = os.path.join(_savedfilesdirname, filename)
    if os.path.exists(filename) and not os.path.exists(savename):
        os.link(filename, savename)

    show_gallery(form, _filename=savename)


def do_delete(form):
    filename = form.getvalue('filename')

    cwd = os.getcwd()
    if (os.path.join(cwd, _savedfilesdirname) !=
            os.path.dirname(os.path.abspath(filename)) or
            not filename.endswith('.jpg')):
        raise Exception('Someone is trying to hack in.  I see you!')

    if os.path.exists(filename):
        os.unlink(filename)

    show_gallery(form)


def get_random_file(dirname):
    return os.path.join(dirname, choice(os.listdir(dirname)))


def show_empty_gallery():
    return do_memeshup()


def show_gallery(form=None, _filename=None):
    if _filename:
        filename = _filename
    elif form is None or not form.has_key('filename') or form.has_key('delete'):
        try:
            filename = get_random_file(_savedfilesdirname)
        except IndexError:
            return show_empty_gallery()
    else:
        filename = form.getvalue('filename')
        delta = form.has_key('next') * 1 + form.has_key('prev') * -1
        if delta != 0:
            files = [os.path.join(_savedfilesdirname, f) for f in
                    os.listdir(_savedfilesdirname)]
            try:
                idx = files.index(filename)
            except ValueError:
                show_empty_gallery()
            else:
                if len(files) <= idx + delta:
                    filename = files[0]
                else:
                    filename = files[idx + delta]

    if not os.path.exists(filename):
        raise Exception("Can't find file to show.")

    print('Content-Type: text/html\n\n')
    try:
        html = open('gallery.html.tmpl', 'r')
    except IOError, e:
        raise e
    else:
        for line in html.readlines():
            idx = line.find('@FILENAME@')
            if idx != -1:
                line = line[:idx] + filename + line[idx+10:]
            print(line)

    return 0


def _do_memeshup():
    if randint(0, 100) == 100:
        cleantempimages()

    vomitfreesince, pandacache = loadflickrdata()
    memecache = loadmemedata(pandacache)

    for i in range(200):
        try:
            if not pandacache or not memecache:
                notify('No items left.')
                raise Exception('No items left.')
            url = pandacache.pop()
            meme = memecache.pop()

            image, filename = getimage(url)
            filename = os.path.basename(filename)
            macro = superimpose(meme, image)
        except TryAgain:
            notify("Can't fit text in image.  Trying again.")
            continue
        else:
            do_output(macro, filename)
            break
    else:
        notify('Tried 200 times, still no go.')
        raise Exception

    savecache(_pandacachebasename, (vomitfreesince, pandacache))
    savecache(_memecachebasename, memecache)

    return 0


def do_memeshup():
    ret = 0
    while True:
        try:
            # um hello python why does sys.exit(0) result in an exception?
            ret = _do_memeshup()
            break
        except BlowUpTheWorldAndRestart, e:
            # This is for when everything goes to shit and I don't know why,
            # and for some reason killing the cache fixes it.
            killcache(_pandacachebasename)
            killcache(_memecachebasename)
        except Exception, e:
            ret = 1
            break

    return ret


def main(argv):
    form = cgi.FieldStorage()
    if form.has_key('save'):
        return do_save(form)
    elif form.has_key('delete'):
        return do_delete(form)
    elif form.has_key('gallery'):
        return show_gallery(form)
    else:
        return do_memeshup()


if __name__ == '__main__':
    #sys.exit(main(sys.argv))
    ret = 0
    try:
        ret = main(sys.argv)
    except Exception, e:
        # shit, son
        notify('%s\n' % str(e))
        traceback.print_exc(file=sys.stderr)
        print('Content-type: text/plain\n\n')
        print("Uh-oh.  Script broke.  If you're me, check your logs.")
        print('To the rest of you, sorry.  Try again in a bit, and if it '
                "doesn't fix itself, let me know.")
        ret = 1

    sys.exit(ret)

