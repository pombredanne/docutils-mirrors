#! /usr/bin/env python
"""
:Authors: David Goodger
:Contact: goodger@users.sourceforge.net
:Revision: $Revision$
:Date: $Date$
:Copyright: This module has been placed in the public domain.

Transforms for resolving references:

- `Hyperlinks`: Used to resolve hyperlink targets and references.
- `Footnotes`: Resolve footnote numbering and references.
- `Substitutions`: Resolve substitutions.
"""

__docformat__ = 'reStructuredText'

import re
from docutils import nodes, utils
from docutils.transforms import TransformError, Transform


class Hyperlinks(Transform):

    """Resolve the various types of hyperlink targets and references."""

    def transform(self):
        self.resolve_chained_targets()
        self.resolve_anonymous()
        self.resolve_indirect()
        self.resolve_external_targets()
        self.resolve_internal_targets()

    def resolve_chained_targets(self):
        """
        Attributes "refuri" and "refname" are migrated from the final direct
        target up the chain of contiguous adjacent internal targets, using
        `ChainedTargetResolver`.
        """
        visitor = ChainedTargetResolver(self.document)
        self.document.walk(visitor)

    def resolve_anonymous(self):
        """
        Link anonymous references to targets.  Given::

            <paragraph>
                <reference anonymous="1">
                    internal
                <reference anonymous="1">
                    external
            <target anonymous="1" id="id1">
            <target anonymous="1" id="id2" refuri="http://external">

        Corresponding references are linked via "refid" or resolved via
        "refuri"::

            <paragraph>
                <reference anonymous="1" refid="id1">
                    text
                <reference anonymous="1" refuri="http://external">
                    external
            <target anonymous="1" id="id1">
            <target anonymous="1" id="id2" refuri="http://external">
        """
        if len(self.document.anonymous_refs) \
              != len(self.document.anonymous_targets):
            msg = self.document.reporter.error(
                  'Anonymous hyperlink mismatch: %s references but %s '
                  'targets.' % (len(self.document.anonymous_refs),
                                len(self.document.anonymous_targets)))
            self.document.messages += msg
            msgid = self.document.set_id(msg)
            for ref in self.document.anonymous_refs:
                prb = nodes.problematic(
                      ref.rawsource, ref.rawsource, refid=msgid)
                prbid = self.document.set_id(prb)
                msg.add_backref(prbid)
                ref.parent.replace(ref, prb)
            return
        for i in range(len(self.document.anonymous_refs)):
            ref = self.document.anonymous_refs[i]
            target = self.document.anonymous_targets[i]
            if target.hasattr('refuri'):
                ref['refuri'] = target['refuri']
                ref.resolved = 1
            else:
                ref['refid'] = target['id']
                self.document.note_refid(ref)
            target.referenced = 1

    def resolve_indirect(self):
        """
        a) Indirect external references::

               <paragraph>
                   <reference refname="indirect external">
                       indirect external
               <target id="id1" name="direct external"
                   refuri="http://indirect">
               <target id="id2" name="indirect external"
                   refname="direct external">

           The "refuri" attribute is migrated back to all indirect targets
           from the final direct target (i.e. a target not referring to
           another indirect target)::

               <paragraph>
                   <reference refname="indirect external">
                       indirect external
               <target id="id1" name="direct external"
                   refuri="http://indirect">
               <target id="id2" name="indirect external"
                   refuri="http://indirect">

           Once the attribute is migrated, the preexisting "refname" attribute
           is dropped.

        b) Indirect internal references::

               <target id="id1" name="final target">
               <paragraph>
                   <reference refname="indirect internal">
                       indirect internal
               <target id="id2" name="indirect internal 2"
                   refname="final target">
               <target id="id3" name="indirect internal"
                   refname="indirect internal 2">

           Targets which indirectly refer to an internal target become one-hop
           indirect (their "refid" attributes are directly set to the internal
           target's "id"). References which indirectly refer to an internal
           target become direct internal references::

               <target id="id1" name="final target">
               <paragraph>
                   <reference refid="id1">
                       indirect internal
               <target id="id2" name="indirect internal 2" refid="id1">
               <target id="id3" name="indirect internal" refid="id1">
        """
        for target in self.document.indirect_targets:
            if not target.resolved:
                self.resolve_indirect_target(target)
            self.resolve_indirect_references(target)

    def resolve_indirect_target(self, target):
        refname = target['refname']
        reftarget = None
        if self.document.explicit_targets.has_key(refname):
            reftarget = self.document.explicit_targets[refname]
        elif self.document.implicit_targets.has_key(refname):
            reftarget = self.document.implicit_targets[refname]
        if not reftarget:
            self.nonexistent_indirect_target(target)
            return
        if isinstance(reftarget, nodes.target) \
              and not reftarget.resolved and reftarget.hasattr('refname'):
            self.one_indirect_target(reftarget) # multiply indirect
        if reftarget.hasattr('refuri'):
            target['refuri'] = reftarget['refuri']
            if target.hasattr('name'):
                self.document.note_external_target(target)
        elif reftarget.hasattr('refid'):
            target['refid'] = reftarget['refid']
            self.document.note_refid(target)
        else:
            try:
                target['refid'] = reftarget['id']
                self.document.note_refid(target)
            except KeyError:
                self.nonexistent_indirect_target(target)
                return
        del target['refname']
        target.resolved = 1
        reftarget.referenced = 1

    def nonexistent_indirect_target(self, target):
        naming = ''
        if target.hasattr('name'):
            naming = '"%s" ' % target['name']
            reflist = self.document.refnames[target['name']]
        else:
            reflist = self.document.refnames[target['id']]
        naming += '(id="%s")' % target['id']
        msg = self.document.reporter.warning(
              'Indirect hyperlink target %s refers to target "%s", '
              'which does not exist.' % (naming, target['refname']))
        self.document.messages += msg
        msgid = self.document.set_id(msg)
        for ref in reflist:
            prb = nodes.problematic(
                  ref.rawsource, ref.rawsource, refid=msgid)
            prbid = self.document.set_id(prb)
            msg.add_backref(prbid)
            ref.parent.replace(ref, prb)
        target.resolved = 1

    def resolve_indirect_references(self, target):
        if target.hasattr('refid'):
            attname = 'refid'
            call_if_named = 0
            call_method = self.document.note_refid
        elif target.hasattr('refuri'):
            attname = 'refuri'
            call_if_named = 1
            call_method = self.document.note_external_target
        else:
            return
        attval = target[attname]
        if target.hasattr('name'):
            name = target['name']
            try:
                reflist = self.document.refnames[name]
            except KeyError, instance:
                if target.referenced:
                    return
                msg = self.document.reporter.info(
                      'Indirect hyperlink target "%s" is not referenced.'
                      % name)
                self.document.messages += msg
                target.referenced = 1
                return
            delatt = 'refname'
        else:
            id = target['id']
            try:
                reflist = self.document.refids[id]
            except KeyError, instance:
                if target.referenced:
                    return
                msg = self.document.reporter.info(
                      'Indirect hyperlink target id="%s" is not referenced.'
                      % id)
                self.document.messages += msg
                target.referenced = 1
                return
            delatt = 'refid'
        for ref in reflist:
            if ref.resolved:
                continue
            del ref[delatt]
            ref[attname] = attval
            if not call_if_named or ref.hasattr('name'):
                call_method(ref)
            ref.resolved = 1
            if isinstance(ref, nodes.target):
                self.resolve_indirect_references(ref)
        target.referenced = 1

    def resolve_external_targets(self):
        """
        Given::

            <paragraph>
                <reference refname="direct external">
                    direct external
            <target id="id1" name="direct external" refuri="http://direct">

        The "refname" attribute is replaced by the direct "refuri" attribute::

            <paragraph>
                <reference refuri="http://direct">
                    direct external
            <target id="id1" name="direct external" refuri="http://direct">
        """
        for target in self.document.external_targets:
            if target.hasattr('refuri') and target.hasattr('name'):
                name = target['name']
                refuri = target['refuri']
                try:
                    reflist = self.document.refnames[name]
                except KeyError, instance:
                    if target.referenced:
                        continue
                    msg = self.document.reporter.info(
                          'External hyperlink target "%s" is not referenced.'
                          % name)
                    self.document.messages += msg
                    target.referenced = 1
                    continue
                for ref in reflist:
                    if ref.resolved:
                        continue
                    del ref['refname']
                    ref['refuri'] = refuri
                    ref.resolved = 1
                target.referenced = 1

    def resolve_internal_targets(self):
        """
        Given::

            <paragraph>
                <reference refname="direct internal">
                    direct internal
            <target id="id1" name="direct internal">

        The "refname" attribute is replaced by "refid" linking to the target's
        "id"::

            <paragraph>
                <reference refid="id1">
                    direct internal
            <target id="id1" name="direct internal">
        """
        for target in self.document.internal_targets:
            if target.hasattr('refuri') or target.hasattr('refid') \
                  or not target.hasattr('name'):
                continue
            name = target['name']
            refid = target['id']
            try:
                reflist = self.document.refnames[name]
            except KeyError, instance:
                if target.referenced:
                    continue
                msg = self.document.reporter.info(
                      'Internal hyperlink target "%s" is not referenced.'
                      % name)
                self.document.messages += msg
                target.referenced = 1
                continue
            for ref in reflist:
                if ref.resolved:
                    continue
                del ref['refname']
                ref['refid'] = refid
                ref.resolved = 1
            target.referenced = 1


class ChainedTargetResolver(nodes.SparseNodeVisitor):

    """
    Copy reference attributes up the length of a hyperlink target chain.

    "Chained targets" are multiple adjacent internal hyperlink targets which
    "point to" an external or indirect target.  After the transform, all
    chained targets will effectively point to the same place.

    Given the following ``document`` as input::

        <document>
            <target id="a" name="a">
            <target id="b" name="b">
            <target id="c" name="c" refuri="http://chained.external.targets">
            <target id="d" name="d">
            <paragraph>
                I'm known as "d".
            <target id="e" name="e">
            <target id="id1">
            <target id="f" name="f" refname="d">

    ``ChainedTargetResolver(document).walk()`` will transform the above into::

        <document>
            <target id="a" name="a" refuri="http://chained.external.targets">
            <target id="b" name="b" refuri="http://chained.external.targets">
            <target id="c" name="c" refuri="http://chained.external.targets">
            <target id="d" name="d">
            <paragraph>
                I'm known as "d".
            <target id="e" name="e" refname="d">
            <target id="id1" refname="d">
            <target id="f" name="f" refname="d">
    """

    def unknown_visit(self, node):
        pass

    def visit_target(self, node):
        if node.hasattr('refuri'):
            attname = 'refuri'
            call_if_named = self.document.note_external_target
        elif node.hasattr('refname'):
            attname = 'refname'
            call_if_named = self.document.note_indirect_target
        elif node.hasattr('refid'):
            attname = 'refid'
            call_if_named = None
        else:
            return
        attval = node[attname]
        index = node.parent.index(node)
        for i in range(index - 1, -1, -1):
            sibling = node.parent[i]
            if not isinstance(sibling, nodes.target) \
                  or sibling.hasattr('refuri') \
                  or sibling.hasattr('refname') \
                  or sibling.hasattr('refid'):
                break
            sibling[attname] = attval
            if sibling.hasattr('name') and call_if_named:
                call_if_named(sibling)


class Footnotes(Transform):

    """
    Assign numbers to autonumbered footnotes, and resolve links to footnotes,
    citations, and their references.

    Given the following ``document`` as input::

        <document>
            <paragraph>
                A labeled autonumbered footnote referece:
                <footnote_reference auto="1" id="id1" refname="footnote">
            <paragraph>
                An unlabeled autonumbered footnote referece:
                <footnote_reference auto="1" id="id2">
            <footnote auto="1" id="id3">
                <paragraph>
                    Unlabeled autonumbered footnote.
            <footnote auto="1" id="footnote" name="footnote">
                <paragraph>
                    Labeled autonumbered footnote.

    Auto-numbered footnotes have attribute ``auto="1"`` and no label.
    Auto-numbered footnote_references have no reference text (they're
    empty elements). When resolving the numbering, a ``label`` element
    is added to the beginning of the ``footnote``, and reference text
    to the ``footnote_reference``.

    The transformed result will be::

        <document>
            <paragraph>
                A labeled autonumbered footnote referece:
                <footnote_reference auto="1" id="id1" refid="footnote">
                    2
            <paragraph>
                An unlabeled autonumbered footnote referece:
                <footnote_reference auto="1" id="id2" refid="id3">
                    1
            <footnote auto="1" id="id3" backrefs="id2">
                <label>
                    1
                <paragraph>
                    Unlabeled autonumbered footnote.
            <footnote auto="1" id="footnote" name="footnote" backrefs="id1">
                <label>
                    2
                <paragraph>
                    Labeled autonumbered footnote.

    Note that the footnotes are not in the same order as the references.

    The labels and reference text are added to the auto-numbered ``footnote``
    and ``footnote_reference`` elements.  Footnote elements are backlinked to
    their references via "refids" attributes.  References are assigned "id"
    and "refid" attributes.

    After adding labels and reference text, the "auto" attributes can be
    ignored.
    """

    autofootnote_labels = None
    """Keep track of unlabeled autonumbered footnotes."""

    symbols = [
          # Entries 1-4 and 6 below are from section 12.51 of
          # The Chicago Manual of Style, 14th edition.
          '*',                          # asterisk/star
          u'\u2020',                    # dagger &dagger;
          u'\u2021',                    # double dagger &Dagger;
          u'\u00A7',                    # section mark &sect;
          u'\u00B6',                    # paragraph mark (pilcrow) &para;
                                        # (parallels ['||'] in CMoS)
          '#',                          # number sign
          # The entries below were chosen arbitrarily.
          u'\u2660',                    # spade suit &spades;
          u'\u2665',                    # heart suit &hearts;
          u'\u2666',                    # diamond suit &diams;
          u'\u2663',                    # club suit &clubs;
          ]

    def transform(self):
        self.autofootnote_labels = []
        startnum = self.document.autofootnote_start
        self.document.autofootnote_start = self.number_footnotes(startnum)
        self.number_footnote_references(startnum)
        self.symbolize_footnotes()
        self.resolve_footnotes_and_citations()

    def number_footnotes(self, startnum):
        """
        Assign numbers to autonumbered footnotes.

        For labeled autonumbered footnotes, copy the number over to
        corresponding footnote references.
        """
        for footnote in self.document.autofootnotes:
            while 1:
                label = str(startnum)
                startnum += 1
                if not self.document.explicit_targets.has_key(label):
                    break
            footnote.insert(0, nodes.label('', label))
            if footnote.hasattr('dupname'):
                continue
            if footnote.hasattr('name'):
                name = footnote['name']
                for ref in self.document.footnote_refs.get(name, []):
                    ref += nodes.Text(label)
                    ref.delattr('refname')
                    ref['refid'] = footnote['id']
                    footnote.add_backref(ref['id'])
                    self.document.note_refid(ref)
                    ref.resolved = 1
            else:
                footnote['name'] = label
                self.document.note_explicit_target(footnote, footnote)
                self.autofootnote_labels.append(label)
        return startnum

    def number_footnote_references(self, startnum):
        """Assign numbers to autonumbered footnote references."""
        i = 0
        for ref in self.document.autofootnote_refs:
            if ref.resolved or ref.hasattr('refid'):
                continue
            try:
                label = self.autofootnote_labels[i]
            except IndexError:
                msg = self.document.reporter.error(
                      'Too many autonumbered footnote references: only %s '
                      'corresponding footnotes available.'
                      % len(self.autofootnote_labels))
                msgid = self.document.set_id(msg)
                self.document.messages += msg
                for ref in self.document.autofootnote_refs[i:]:
                    if ref.resolved or ref.hasattr('refname'):
                        continue
                    prb = nodes.problematic(
                          ref.rawsource, ref.rawsource, refid=msgid)
                    prbid = self.document.set_id(prb)
                    msg.add_backref(prbid)
                    ref.parent.replace(ref, prb)
                break
            ref += nodes.Text(label)
            footnote = self.document.explicit_targets[label]
            ref['refid'] = footnote['id']
            self.document.note_refid(ref)
            footnote.add_backref(ref['id'])
            ref.resolved = 1
            i += 1

    def symbolize_footnotes(self):
        """Add symbols indexes to "[*]"-style footnotes and references."""
        labels = []
        for footnote in self.document.symbol_footnotes:
            reps, index = divmod(self.document.symbol_footnote_start,
                                 len(self.symbols))
            labeltext = self.symbols[index] * (reps + 1)
            labels.append(labeltext)
            footnote.insert(0, nodes.label('', labeltext))
            self.document.symbol_footnote_start += 1
            self.document.set_id(footnote)
        i = 0
        for ref in self.document.symbol_footnote_refs:
            try:
                ref += nodes.Text(labels[i])
            except IndexError:
                msg = self.document.reporter.error(
                      'Too many symbol footnote references: only %s '
                      'corresponding footnotes available.' % len(labels))
                msgid = self.set_id(msg)
                self.document.messages += msg
                for ref in self.document.symbol_footnote_refs[i:]:
                    if ref.resolved or ref.hasattr('refid'):
                        continue
                    prb = nodes.problematic(
                          ref.rawsource, ref.rawsource, refid=msgid)
                    prbid = self.document.set_id(prb)
                    msg.add_backref(prbid)
                    ref.parent.replace(ref, prb)
                break
            footnote = self.document.symbol_footnotes[i]
            ref['refid'] = footnote['id']
            self.document.note_refid(ref)
            footnote.add_backref(ref['id'])
            i += 1

    def resolve_footnotes_and_citations(self):
        """
        Link manually-labeled footnotes and citations to/from their
        references.
        """
        for footnote in self.document.footnotes:
            label = footnote['name']
            if self.document.footnote_refs.has_key(label):
                reflist = self.document.footnote_refs[label]
                self.resolve_references(footnote, reflist)
        for citation in self.document.citations:
            label = citation['name']
            if self.document.citation_refs.has_key(label):
                reflist = self.document.citation_refs[label]
                self.resolve_references(citation, reflist)

    def resolve_references(self, note, reflist):
        id = note['id']
        for ref in reflist:
            if ref.resolved:
                continue
            ref.delattr('refname')
            ref['refid'] = id
            note.add_backref(ref['id'])
            ref.resolved = 1
        note.resolved = 1


class Substitutions(Transform):

    """
    Given the following ``document`` as input::

        <document>
            <paragraph>
                The
                <substitution_reference refname="biohazard">
                    biohazard
                 symbol is deservedly scary-looking.
            <substitution_definition name="biohazard">
                <image alt="biohazard" uri="biohazard.png">

    The ``substitution_reference`` will simply be replaced by the
    contents of the corresponding ``substitution_definition``.

    The transformed result will be::

        <document>
            <paragraph>
                The
                <image alt="biohazard" uri="biohazard.png">
                 symbol is deservedly scary-looking.
            <substitution_definition name="biohazard">
                <image alt="biohazard" uri="biohazard.png">
    """

    def transform(self):
        defs = self.document.substitution_defs
        for refname, refs in self.document.substitution_refs.items():
            for ref in refs:
                if defs.has_key(refname):
                    ref.parent.replace(ref, defs[refname].get_children())
                else:
                    msg = self.document.reporter.error(
                          'Undefined substitution referenced: "%s".'
                          % refname)
                    msgid = self.document.set_id(msg)
                    self.document.messages += msg
                    prb = nodes.problematic(
                          ref.rawsource, ref.rawsource, refid=msgid)
                    prbid = self.document.set_id(prb)
                    msg.add_backref(prbid)
                    ref.parent.replace(ref, prb)
        self.document.substitution_refs = None  # release replaced references
